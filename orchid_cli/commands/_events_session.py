"""Shared session helper for the four event commands (Phase 5).

Mirrors :mod:`._session` but additionally wires up the events
runtime — ``signals`` / ``jobs`` / ``runs`` / ``schedules`` all
need a live :class:`EventsRuntime` to read from / write to.

The CLI runs the events block **locally**: it bootstraps Orchid,
calls :func:`orchid_ai.events.bootstrap.start_events`, and operates
on the same SQLite (or shared-pool Postgres) backend the YAML
configures.  This matches how ``orchid chat send`` runs the graph
locally rather than hitting ``orchid-api`` over HTTP — the CLI is a
peer to the API, not a client of it.

Implications:

- The CLI sees every signal / run regardless of caller identity
  (it operates as a local operator tool).  Visibility filtering
  is enforced at the API layer; on the CLI side the operator is
  expected to have direct DB access already, so a parallel filter
  would be security theatre.
- Producers (HTTPIngestionProducer, SchedulerProducer,
  RelayRecoveryProducer) declared in YAML do NOT start by default
  in the CLI — they're long-running and don't make sense for a
  short-lived ``orchid signals emit`` invocation.  The CLI starts
  the dispatcher + processor + stores only.  Operators wanting a
  long-running producer should run ``orchid-api`` instead.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from orchid_ai import Orchid
from orchid_ai.events.bootstrap import EventsRuntime, start_events, stop_events

from ..bootstrap import bootstrap

logger = logging.getLogger(__name__)


async def resolve_events_session(
    config_path: str,
    *,
    start_producers: bool = False,
) -> tuple[Orchid, EventsRuntime]:
    """Boot Orchid AND the events runtime.

    ``start_producers`` defaults False — short-lived CLI commands
    should not start long-running producers.  Pass ``True`` only
    from a hypothetical ``orchid events serve`` command (not in
    v1).
    """
    orchid = await bootstrap(config_path)

    if orchid.config.events is None or not orchid.config.events.enabled:
        # Tear orchid down before raising so we don't leak a chat
        # storage handle.  Typer surfaces the error message to the
        # operator unchanged.
        await orchid.close()
        raise RuntimeError(
            "events block disabled in agents.yaml — set events.enabled=true "
            "to use the signals/jobs/runs/schedules commands"
        )

    events = await start_events(
        events_config=orchid.config.events,
        chat_storage=orchid.chat_repo,
        identity_resolver=None,  # CLI doesn't resolve users
        session_warmer=orchid.session_warmer,
        known_agents=set(orchid.config.agents.keys()),
    )
    if not start_producers:
        # Stop any producers ``start_events`` already started — short-
        # lived CLI invocations don't want a SchedulerProducer firing
        # cron triggers in the background while the operator's
        # inspecting state.
        for producer in list(events.producers):
            try:
                await producer.stop()
            except Exception:
                logger.warning(
                    "Failed to stop producer %s during CLI bootstrap",
                    getattr(producer, "name", type(producer).__name__),
                )
        events.producers = []
        events.http_producer = None
    return orchid, events


@asynccontextmanager
async def events_session(config_path: str, *, start_producers: bool = False):
    """Async context manager: yields ``(orchid, events_runtime)`` and
    cleans up both on exit, even if the wrapped block raises."""
    orchid, events = await resolve_events_session(config_path, start_producers=start_producers)
    try:
        yield orchid, events
    finally:
        try:
            await stop_events(events)
        finally:
            await orchid.close()


def require_events(events: EventsRuntime) -> None:
    """Defensive check used by command bodies — raises a clean
    runtime error when the runtime came back disabled (which
    happens when the YAML has events.enabled=false even though
    the dataclass instantiated)."""
    if not events.enabled:
        raise RuntimeError(
            "events runtime is disabled — check that agents.yaml has "
            "events.enabled=true and that the store / queue blocks "
            "are populated"
        )


def now_or_iso(value: Any) -> str:
    """Render a datetime / None as ISO8601 (or empty string)."""
    if value is None:
        return ""
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
