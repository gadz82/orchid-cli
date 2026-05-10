"""``orchid jobs`` — list registered triggers + their runs.

| Command | Purpose |
|---|---|
| ``orchid jobs list``                    | Active triggers from agents.yaml. |
| ``orchid jobs runs <trigger_id>``       | Recent runs for a trigger. |
"""

from __future__ import annotations

import asyncio
import logging

import typer
from rich.console import Console
from rich.table import Table

from ._events_session import events_session, now_or_iso, require_events

app = typer.Typer(
    name="jobs",
    help="Pollen + Bloom — inspect triggers (jobs) and their runs.",
    no_args_is_help=True,
)
console = Console()
logger = logging.getLogger(__name__)


# ── list ────────────────────────────────────────────────────


@app.command("list")
def list_command(
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    """List every active trigger (read-only in v1)."""
    asyncio.run(_list_async(config_path=config_path))


async def _list_async(*, config_path: str) -> None:
    async with events_session(config_path) as (_orchid, events):
        require_events(events)
        triggers = list(events.trigger_registry.all())
    if not triggers:
        console.print("[yellow]No triggers registered.[/yellow]")
        return

    table = Table(title="Triggers", show_lines=False)
    table.add_column("trigger_id", style="cyan", no_wrap=True)
    table.add_column("parallelism")
    table.add_column("visibility")
    table.add_column("respect_chat_binding")
    for t in triggers:
        table.add_row(
            t.trigger_id,
            getattr(t, "parallelism", "per_user"),
            getattr(t, "visibility", "admin"),
            "yes" if getattr(t, "respect_chat_binding", False) else "no",
        )
    console.print(table)


# ── runs <trigger_id> ───────────────────────────────────────


@app.command("runs")
def runs_command(
    trigger_id: str = typer.Argument(..., help="Trigger id from agents.yaml."),
    status: str | None = typer.Option(None, "--status", help="Filter by status (succeeded / failed / pending / …)."),
    limit: int = typer.Option(50, "--limit", "-l", min=1, max=500),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    """List recent runs for a specific trigger."""
    asyncio.run(
        _runs_async(
            config_path=config_path,
            trigger_id=trigger_id,
            status=status,
            limit=limit,
        )
    )


async def _runs_async(*, config_path: str, trigger_id: str, status: str | None, limit: int) -> None:
    async with events_session(config_path) as (_orchid, events):
        require_events(events)
        if events.trigger_registry.get(trigger_id) is None:
            console.print(f"[red]Trigger {trigger_id!r} not registered.[/red]")
            raise typer.Exit(code=1)
        rows = await events.job_store.list(trigger_id=trigger_id, status=status, limit=limit)

    if not rows:
        console.print(f"[yellow]No runs for trigger {trigger_id!r}.[/yellow]")
        return

    table = Table(title=f"Runs for trigger {trigger_id!r}", show_lines=False)
    table.add_column("run_id", style="cyan", no_wrap=True)
    table.add_column("attempt", style="dim")
    table.add_column("status", style="green")
    table.add_column("agent")
    table.add_column("visibility")
    table.add_column("queued_at", style="dim")
    table.add_column("finished_at", style="dim")
    for r in rows:
        table.add_row(
            str(r.run_id),
            str(r.attempt_number),
            r.status.value,
            r.spec.agent_name,
            r.spec.visibility,
            now_or_iso(r.queued_at),
            now_or_iso(r.finished_at),
        )
    console.print(table)
