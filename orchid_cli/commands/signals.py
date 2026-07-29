"""``orchid signals`` — emit / list / show.

Operates on the local events runtime (same SQLite / Postgres backend
the YAML configures).  Mirrors §17 of the spec but runs in-process
rather than over HTTP — see ``_events_session.py`` for the
rationale.

Subcommands
-----------

- ``orchid signals emit <type> [--payload JSON] [--source S]
  [--tenant T] [--user U] [--dedupe-key K] [--correlation C]
  [--config orchid.yml]``

  Builds a :class:`SignalEnvelope`, hands it to the dispatcher,
  prints ``signal_id`` + ``deduplicated``.

- ``orchid signals list [--type T] [--since 1h] [--limit 50]
  [--config orchid.yml]``

  Recent signals — table view.

- ``orchid signals show <id> [--config orchid.yml]``

  Detailed view with payload + identity claim + chat binding.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import json as _json
import logging
import re
import uuid as _uuid
from typing import Any

import typer
from orchid_ai.core.events.signal import SignalEnvelope
from rich.console import Console
from rich.table import Table

from ._events_session import events_session, now_or_iso, require_events

app = typer.Typer(
    name="signals",
    help="Pollen + Bloom — emit / list / inspect signals.",
    no_args_is_help=True,
)
console = Console()
logger = logging.getLogger(__name__)


# ── emit ────────────────────────────────────────────────────


@app.command("emit")
def emit_command(
    type: str = typer.Argument(..., help="Signal type (e.g. 'support.ticket.created')"),
    payload: str = typer.Option(
        "{}",
        "--payload",
        "-p",
        help="JSON payload (object).  Use '@file.json' to read from disk.",
    ),
    source: str = typer.Option("cli:orchid", "--source", "-s", help="Signal source identifier."),
    tenant: str = typer.Option("default", "--tenant", "-t", help="Tenant key."),
    user: str | None = typer.Option(None, "--user", "-u", help="Originating user_id (optional)."),
    dedupe_key: str | None = typer.Option(None, "--dedupe-key", "-k", help="Idempotency key."),
    correlation_id: str | None = typer.Option(None, "--correlation-id", help="Correlation id linking related signals."),
    identity: str | None = typer.Option(
        None,
        "--identity",
        help='Identity claim as JSON (e.g. \'{"mode":"service_account","name":"bot"}\')',
    ),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    """Emit a signal through the local dispatcher."""
    asyncio.run(
        _emit_async(
            config_path=config_path,
            signal_type=type,
            payload_raw=payload,
            source=source,
            tenant=tenant,
            user=user,
            dedupe_key=dedupe_key,
            correlation_id=correlation_id,
            identity_raw=identity,
        )
    )


async def _emit_async(
    *,
    config_path: str,
    signal_type: str,
    payload_raw: str,
    source: str,
    tenant: str,
    user: str | None,
    dedupe_key: str | None,
    correlation_id: str | None,
    identity_raw: str | None,
) -> None:
    payload = _parse_json_arg(payload_raw, "--payload")
    identity_claim = _parse_json_arg(identity_raw, "--identity") if identity_raw is not None else None

    async with events_session(config_path) as (_orchid, events):
        require_events(events)
        envelope = SignalEnvelope(
            type=signal_type,
            payload=payload if isinstance(payload, dict) else {},
            source=source,
            occurred_at=_dt.datetime.now(tz=_dt.UTC),
            tenant_key=tenant,
            user_id=user,
            correlation_id=correlation_id,
            dedupe_key=dedupe_key,
            identity_claim=identity_claim,
        )
        result = await events.dispatcher.ingest(envelope)
    console.print(f"[green]signal_id[/green]={result.signal_id} [cyan]deduplicated[/cyan]={result.deduplicated}")


# ── list ────────────────────────────────────────────────────


@app.command("list")
def list_command(
    type_filter: str | None = typer.Option(None, "--type", "-T", help="Filter by signal type."),
    tenant: str | None = typer.Option(None, "--tenant", help="Filter by tenant_key."),
    since: str | None = typer.Option(
        None,
        "--since",
        "-s",
        help="Only signals from the last N (e.g. '15m', '2h', '1d') OR ISO8601.",
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Max rows.", min=1, max=1000),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    """List recent signals."""
    asyncio.run(
        _list_async(
            config_path=config_path,
            type_filter=type_filter,
            tenant=tenant,
            since=since,
            limit=limit,
        )
    )


async def _list_async(
    *,
    config_path: str,
    type_filter: str | None,
    tenant: str | None,
    since: str | None,
    limit: int,
) -> None:
    since_dt = _parse_since(since)
    async with events_session(config_path) as (_orchid, events):
        require_events(events)
        rows = await events.signal_store.list(
            type=type_filter,
            tenant_key=tenant,
            since=since_dt,
            limit=limit,
        )
    if not rows:
        console.print("[yellow]No signals.[/yellow]")
        return

    table = Table(title="Signals", show_lines=False)
    table.add_column("signal_id", style="cyan", no_wrap=True)
    table.add_column("type", style="green")
    table.add_column("source")
    table.add_column("tenant")
    table.add_column("dedupe_key")
    table.add_column("persisted_at", style="dim")
    for sig in rows:
        table.add_row(
            str(sig.signal_id),
            sig.type,
            sig.source,
            sig.tenant_key,
            sig.dedupe_key or "",
            now_or_iso(sig.persisted_at),
        )
    console.print(table)


# ── show ────────────────────────────────────────────────────


@app.command("show")
def show_command(
    signal_id: str = typer.Argument(..., help="Signal UUID."),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    """Show full detail for a signal, including payload and runs."""
    asyncio.run(_show_async(config_path=config_path, signal_id=signal_id))


async def _show_async(*, config_path: str, signal_id: str) -> None:
    try:
        sid = _uuid.UUID(signal_id)
    except ValueError:
        console.print(f"[red]Invalid signal id: {signal_id!r}[/red]")
        raise typer.Exit(code=1)

    async with events_session(config_path) as (_orchid, events):
        require_events(events)
        signal = await events.signal_store.get(sid)
        if signal is None:
            console.print(f"[red]Signal {signal_id} not found.[/red]")
            raise typer.Exit(code=1)
        runs = await events.job_store.list(limit=200)
        related = [r for r in runs if r.spec.signal_id == sid]

    payload_pretty = _json.dumps(signal.payload, indent=2, default=str)
    console.print(f"[bold]signal_id[/bold]: {signal.signal_id}")
    console.print(f"[bold]type[/bold]: {signal.type}")
    console.print(f"[bold]source[/bold]: {signal.source}")
    console.print(f"[bold]tenant_key[/bold]: {signal.tenant_key}")
    console.print(f"[bold]user_id[/bold]: {signal.user_id or ''}")
    console.print(f"[bold]correlation_id[/bold]: {signal.correlation_id or ''}")
    console.print(f"[bold]dedupe_key[/bold]: {signal.dedupe_key or ''}")
    console.print(f"[bold]occurred_at[/bold]: {now_or_iso(signal.occurred_at)}")
    console.print(f"[bold]persisted_at[/bold]: {now_or_iso(signal.persisted_at)}")
    console.print(f"[bold]relay_status[/bold]: {signal.relay_status}")
    console.print(
        f"[bold]identity_claim[/bold]: "
        f"{_json.dumps(signal.identity_claim, default=str) if signal.identity_claim else ''}"
    )
    console.print(
        f"[bold]chat_binding[/bold]: {_json.dumps(signal.chat_binding, default=str) if signal.chat_binding else ''}"
    )
    console.print("\n[bold cyan]payload[/bold cyan]:")
    console.print(payload_pretty)

    if related:
        console.print(f"\n[bold magenta]runs[/bold magenta] ({len(related)}):")
        run_table = Table(show_lines=False)
        run_table.add_column("run_id", style="cyan", no_wrap=True)
        run_table.add_column("trigger_id")
        run_table.add_column("attempt", style="dim")
        run_table.add_column("status", style="green")
        run_table.add_column("queued_at", style="dim")
        for r in related:
            run_table.add_row(
                str(r.run_id),
                r.spec.trigger_id,
                str(r.attempt_number),
                r.status.value,
                now_or_iso(r.queued_at),
            )
        console.print(run_table)


# ── helpers ─────────────────────────────────────────────────


def _parse_json_arg(raw: str, label: str) -> Any:
    """Parse a JSON arg or read from ``@file.json``."""
    raw = raw.strip()
    if raw.startswith("@"):
        try:
            with open(raw[1:], "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            console.print(f"[red]Cannot read {label} file {raw[1:]!r}: {exc}[/red]")
            raise typer.Exit(code=1) from exc
    try:
        return _json.loads(raw or "{}")
    except _json.JSONDecodeError as exc:
        console.print(f"[red]Invalid JSON for {label}: {exc}[/red]")
        raise typer.Exit(code=1) from exc


_SINCE_RE = re.compile(r"^(\d+)([smhd])$")


def _parse_since(value: str | None) -> _dt.datetime | None:
    """Parse a ``--since`` value.

    Accepts:

    - ``"15m"`` / ``"2h"`` / ``"1d"`` / ``"30s"`` — relative to now.
    - ``"2026-05-07T08:00:00Z"`` — absolute ISO8601.
    """
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
