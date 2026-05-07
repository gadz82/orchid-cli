"""``orchid runs`` — list / show / retry / cancel.

| Command | Purpose |
|---|---|
| ``orchid runs list [--status s] [--since 1h]`` | Recent runs.       |
| ``orchid runs show <id>``                      | Detailed view.     |
| ``orchid runs retry <id>``                     | Force a fresh attempt by re-enqueueing the originating signal. |
| ``orchid runs cancel <id>``                    | Best-effort cancel. |
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json as _json
import logging
import re
import uuid as _uuid

import typer
from rich.console import Console
from rich.table import Table

from orchid_ai.core.events.job import JobStatus

from ._events_session import events_session, now_or_iso, require_events

app = typer.Typer(
    name="runs",
    help="Pollen + Bloom — inspect / control individual runs.",
    no_args_is_help=True,
)
console = Console()
logger = logging.getLogger(__name__)


# ── list ────────────────────────────────────────────────────


@app.command("list")
def list_command(
    status: str | None = typer.Option(None, "--status", "-S"),
    trigger_id: str | None = typer.Option(None, "--trigger-id", "-t"),
    since: str | None = typer.Option(None, "--since", "-s", help="Window: '15m', '2h', '1d' OR ISO8601."),
    limit: int = typer.Option(50, "--limit", "-l", min=1, max=1000),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    """List recent runs."""
    asyncio.run(
        _list_async(
            config_path=config_path,
            status=status,
            trigger_id=trigger_id,
            since=since,
            limit=limit,
        )
    )


async def _list_async(
    *,
    config_path: str,
    status: str | None,
    trigger_id: str | None,
    since: str | None,
    limit: int,
) -> None:
    since_dt = _parse_since(since)
    async with events_session(config_path) as (_orchid, events):
        require_events(events)
        rows = await events.job_store.list(
            trigger_id=trigger_id,
            status=status,
            since=since_dt,
            limit=limit,
        )
    if not rows:
        console.print("[yellow]No runs.[/yellow]")
        return

    table = Table(title="Runs", show_lines=False)
    table.add_column("run_id", style="cyan", no_wrap=True)
    table.add_column("trigger_id")
    table.add_column("attempt", style="dim")
    table.add_column("status", style="green")
    table.add_column("agent")
    table.add_column("visibility")
    table.add_column("queued_at", style="dim")
    table.add_column("finished_at", style="dim")
    for r in rows:
        table.add_row(
            str(r.run_id),
            r.spec.trigger_id,
            str(r.attempt_number),
            r.status.value,
            r.spec.agent_name,
            r.spec.visibility,
            now_or_iso(r.queued_at),
            now_or_iso(r.finished_at),
        )
    console.print(table)


# ── show ────────────────────────────────────────────────────


@app.command("show")
def show_command(
    run_id: str = typer.Argument(...),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    """Show detailed view of a run, including spec + result."""
    asyncio.run(_show_async(config_path=config_path, run_id=run_id))


async def _show_async(*, config_path: str, run_id: str) -> None:
    try:
        rid = _uuid.UUID(run_id)
    except ValueError:
        console.print(f"[red]Invalid run id: {run_id!r}[/red]")
        raise typer.Exit(code=1)

    async with events_session(config_path) as (_orchid, events):
        require_events(events)
        run = await events.job_store.get(rid)
        if run is None:
            console.print(f"[red]Run {run_id} not found.[/red]")
            raise typer.Exit(code=1)

    console.print(f"[bold]run_id[/bold]: {run.run_id}")
    console.print(f"[bold]trigger_id[/bold]: {run.spec.trigger_id}")
    console.print(f"[bold]signal_id[/bold]: {run.spec.signal_id}")
    console.print(f"[bold]agent[/bold]: {run.spec.agent_name}")
    console.print(f"[bold]attempt_number[/bold]: {run.attempt_number}")
    console.print(f"[bold]status[/bold]: {run.status.value}")
    console.print(f"[bold]visibility[/bold]: {run.spec.visibility}")
    console.print(f"[bold]visibility_user_id[/bold]: {run.spec.visibility_user_id or ''}")
    console.print(f"[bold]parallelism_key[/bold]: {run.spec.parallelism_key}")
    console.print(f"[bold]queued_at[/bold]: {now_or_iso(run.queued_at)}")
    console.print(f"[bold]started_at[/bold]: {now_or_iso(run.started_at)}")
    console.print(f"[bold]finished_at[/bold]: {now_or_iso(run.finished_at)}")
    console.print(f"[bold]next_retry_at[/bold]: {now_or_iso(run.next_retry_at)}")
    if run.error:
        console.print(f"[bold red]error[/bold red]: {run.error}")
    if run.result is not None:
        console.print("\n[bold cyan]result[/bold cyan]:")
        console.print(_json.dumps(run.result, indent=2, default=str))


# ── retry ───────────────────────────────────────────────────


@app.command("retry")
def retry_command(
    run_id: str = typer.Argument(...),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    """Re-enqueue the originating signal so the processor picks a
    fresh attempt with ``attempt_number = previous + 1``."""
    asyncio.run(_retry_async(config_path=config_path, run_id=run_id))


async def _retry_async(*, config_path: str, run_id: str) -> None:
    try:
        rid = _uuid.UUID(run_id)
    except ValueError:
        console.print(f"[red]Invalid run id: {run_id!r}[/red]")
        raise typer.Exit(code=1)

    async with events_session(config_path) as (_orchid, events):
        require_events(events)
        run = await events.job_store.get(rid)
        if run is None:
            console.print(f"[red]Run {run_id} not found.[/red]")
            raise typer.Exit(code=1)
        queue_msg_id = await events.signal_queue.enqueue(run.spec.signal_id)
    console.print(f"[green]requeued[/green] previous_run_id={run.run_id} queue_msg_id={queue_msg_id}")


# ── cancel ──────────────────────────────────────────────────


@app.command("cancel")
def cancel_command(
    run_id: str = typer.Argument(...),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    """Best-effort cancel of a pending / running run."""
    asyncio.run(_cancel_async(config_path=config_path, run_id=run_id))


async def _cancel_async(*, config_path: str, run_id: str) -> None:
    try:
        rid = _uuid.UUID(run_id)
    except ValueError:
        console.print(f"[red]Invalid run id: {run_id!r}[/red]")
        raise typer.Exit(code=1)

    async with events_session(config_path) as (_orchid, events):
        require_events(events)
        run = await events.job_store.get(rid)
        if run is None:
            console.print(f"[red]Run {run_id} not found.[/red]")
            raise typer.Exit(code=1)
        if run.status in (
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        ):
            console.print(f"[yellow]Run already terminal (status={run.status.value}); no-op.[/yellow]")
            return
        run.status = JobStatus.CANCELLED
        run.finished_at = _dt.datetime.now(tz=_dt.UTC)
        run.error = "cancelled via orchid-cli"
        await events.job_store.update(run)
    console.print(f"[green]cancelled[/green] run_id={rid}")


# ── helpers ─────────────────────────────────────────────────


_SINCE_RE = re.compile(r"^(\d+)([smhd])$")


def _parse_since(value: str | None) -> _dt.datetime | None:
    if value is None:
        return None
    m = _SINCE_RE.match(value)
    if m is not None:
        amount = int(m.group(1))
        unit = m.group(2)
        seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        return _dt.datetime.now(tz=_dt.UTC) - _dt.timedelta(seconds=seconds)
    try:
        iso = value.replace("Z", "+00:00")
        parsed = _dt.datetime.fromisoformat(iso)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_dt.UTC)
        return parsed
    except Exception as exc:
        console.print(f"[red]Invalid --since {value!r}: {exc}[/red]")
        raise typer.Exit(code=1) from exc
