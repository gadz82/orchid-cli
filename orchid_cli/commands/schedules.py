"""``orchid schedules`` — list / show / disable / enable.

| Command | Purpose |
|---|---|
| ``orchid schedules list``                  | All schedules. |
| ``orchid schedules show <id>``             | Detailed view. |
| ``orchid schedules disable <id>``          | Toggle off. |
| ``orchid schedules enable <id>``           | Toggle on (symmetric to disable). |

The disable/enable commands flip the ``enabled`` flag in the
:class:`OrchidScheduleStore`.  The next time a scheduler producer
reads the store (``refresh()`` or process restart) the change takes
effect.  In a CLI session the producer isn't running, so the change
is purely persistent — it'll be picked up by whichever long-running
``orchid-api`` (or other host) is responsible for firing schedules.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging

import typer
from rich.console import Console
from rich.table import Table

from ._events_session import events_session, now_or_iso, require_events

app = typer.Typer(
    name="schedules",
    help="Pollen + Bloom — inspect and toggle schedules.",
    no_args_is_help=True,
)
console = Console()
logger = logging.getLogger(__name__)


# ── list ────────────────────────────────────────────────────


@app.command("list")
def list_command(
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    asyncio.run(_list_async(config_path=config_path))


async def _list_async(*, config_path: str) -> None:
    async with events_session(config_path) as (_orchid, events):
        require_events(events)
        rows = list(await events.schedule_store.list())
    if not rows:
        console.print("[yellow]No schedules.[/yellow]")
        return

    table = Table(title="Schedules", show_lines=False)
    table.add_column("schedule_id", style="cyan", no_wrap=True)
    table.add_column("trigger_id")
    table.add_column("cron")
    table.add_column("interval_s", style="dim")
    table.add_column("enabled")
    table.add_column("last_fire_at", style="dim")
    table.add_column("next_fire_at", style="dim")
    for r in rows:
        table.add_row(
            r.schedule_id,
            r.trigger_id,
            r.cron or "",
            str(r.interval_seconds) if r.interval_seconds else "",
            "yes" if r.enabled else "no",
            now_or_iso(r.last_fire_at),
            now_or_iso(r.next_fire_at),
        )
    console.print(table)


# ── show ────────────────────────────────────────────────────


@app.command("show")
def show_command(
    schedule_id: str = typer.Argument(...),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    asyncio.run(_show_async(config_path=config_path, schedule_id=schedule_id))


async def _show_async(*, config_path: str, schedule_id: str) -> None:
    async with events_session(config_path) as (_orchid, events):
        require_events(events)
        record = await events.schedule_store.get(schedule_id)
        if record is None:
            console.print(f"[red]Schedule {schedule_id!r} not found.[/red]")
            raise typer.Exit(code=1)

    console.print(f"[bold]schedule_id[/bold]: {record.schedule_id}")
    console.print(f"[bold]trigger_id[/bold]: {record.trigger_id}")
    console.print(f"[bold]cron[/bold]: {record.cron or ''}")
    console.print(
        f"[bold]interval_seconds[/bold]: {record.interval_seconds if record.interval_seconds is not None else ''}"
    )
    console.print(f"[bold]enabled[/bold]: {record.enabled}")
    console.print(f"[bold]last_fire_at[/bold]: {now_or_iso(record.last_fire_at)}")
    console.print(f"[bold]next_fire_at[/bold]: {now_or_iso(record.next_fire_at)}")
    console.print("\n[bold cyan]identity_claim[/bold cyan]:")
    console.print(_json.dumps(record.identity_claim, indent=2, default=str))


# ── disable / enable ────────────────────────────────────────


@app.command("disable")
def disable_command(
    schedule_id: str = typer.Argument(...),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    asyncio.run(_toggle_async(config_path=config_path, schedule_id=schedule_id, enabled=False))


@app.command("enable")
def enable_command(
    schedule_id: str = typer.Argument(...),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    asyncio.run(_toggle_async(config_path=config_path, schedule_id=schedule_id, enabled=True))


async def _toggle_async(*, config_path: str, schedule_id: str, enabled: bool) -> None:
    async with events_session(config_path) as (_orchid, events):
        require_events(events)
        record = await events.schedule_store.get(schedule_id)
        if record is None:
            console.print(f"[red]Schedule {schedule_id!r} not found.[/red]")
            raise typer.Exit(code=1)
        await events.schedule_store.set_enabled(schedule_id, enabled=enabled)
    state = "enabled" if enabled else "disabled"
    console.print(f"[green]{state}[/green] schedule_id={schedule_id}")
