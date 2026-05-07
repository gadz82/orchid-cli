"""Tests for the four Phase-5 event commands.

Each test patches :func:`orchid_cli.commands._events_session.events_session`
to yield a hand-rolled in-memory ``EventsRuntime`` so the suite runs
without spinning up a real chat storage / scheduler.

Coverage:

- ``signals emit`` builds a SignalEnvelope with the right defaults
  and prints the dispatcher's result.
- ``signals list`` and ``signals show`` render rows correctly.
- ``jobs list`` reads the trigger registry; ``jobs runs <id>`` rejects
  unknown triggers with a non-zero exit code.
- ``runs list`` / ``show`` / ``retry`` / ``cancel`` happy paths +
  not-found cases.
- ``schedules list`` / ``show`` / ``disable`` / ``enable`` happy paths
  and the persistence side-effect (``set_enabled`` was called).
- The session helper short-circuits when ``events.enabled=false``.
"""

from __future__ import annotations

import datetime as _dt
import uuid as _uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from orchid_ai.core.events.dispatcher import OrchidSignalDispatcher
from orchid_ai.core.events.job import JobRun, JobSpec, JobStatus
from orchid_ai.core.events.signal import Signal
from orchid_ai.core.events.store import OrchidScheduleRecord
from orchid_ai.events.bootstrap import EventsRuntime
from orchid_ai.events.queues.inmemory import (
    InMemoryJobStore,
    InMemoryScheduleStore,
    InMemorySignalQueue,
    InMemorySignalStore,
    InMemoryTriggerStore,
)
from orchid_ai.events.registry import InMemoryTriggerRegistry

from orchid_cli.commands import jobs, runs, schedules, signals


runner = CliRunner()


# ── Helpers ─────────────────────────────────────────────────


def _build_runtime() -> tuple[EventsRuntime, dict]:
    """Build a fresh runtime backed by in-memory stores, plus a dict
    of the underlying objects so tests can seed / inspect them."""
    queue = InMemorySignalQueue()
    signal_store = InMemorySignalStore()
    job_store = InMemoryJobStore()
    schedule_store = InMemoryScheduleStore()
    trigger_store = InMemoryTriggerStore()
    registry = InMemoryTriggerRegistry()
    dispatcher = OrchidSignalDispatcher(store=signal_store, queue=queue)
    runtime = EventsRuntime(
        enabled=True,
        dispatcher=dispatcher,
        signal_store=signal_store,
        signal_queue=queue,
        job_store=job_store,
        schedule_store=schedule_store,
        trigger_store=trigger_store,
        trigger_registry=registry,
    )
    return runtime, {
        "queue": queue,
        "signal_store": signal_store,
        "job_store": job_store,
        "schedule_store": schedule_store,
        "registry": registry,
        "dispatcher": dispatcher,
    }


def _patch_session(target_module, runtime: EventsRuntime):
    """Return a patch context that replaces the module-level
    ``events_session`` with one that yields the supplied runtime."""

    @asynccontextmanager
    async def _fake_session(config_path: str, **kwargs):
        yield (MagicMock(), runtime)

    return patch.object(target_module, "events_session", _fake_session)


def _seed_signal(store: InMemorySignalStore) -> Signal:
    sig = Signal(
        type="x",
        payload={"k": "v"},
        source="src",
        occurred_at=_dt.datetime.now(tz=_dt.UTC),
        tenant_key="t-1",
        signal_id=_uuid.uuid4(),
        persisted_at=_dt.datetime.now(tz=_dt.UTC),
    )
    import asyncio

    asyncio.new_event_loop().run_until_complete(store.insert(sig))
    return sig


def _seed_run(
    job_store: InMemoryJobStore,
    *,
    status: JobStatus = JobStatus.SUCCEEDED,
    trigger_id: str = "t1",
) -> JobRun:
    spec = JobSpec(
        trigger_id=trigger_id,
        signal_id=_uuid.uuid4(),
        agent_name="agent",
        prompt="x",
        identity_claim={"mode": "service_account", "name": "bot"},
        correlation_id=None,
        parallelism_key="sa:t-1:bot",
        visibility="admin",
    )
    run = JobRun(
        run_id=_uuid.uuid4(),
        spec=spec,
        attempt_number=1,
        status=status,
        queued_at=_dt.datetime.now(tz=_dt.UTC),
        started_at=_dt.datetime.now(tz=_dt.UTC),
        finished_at=_dt.datetime.now(tz=_dt.UTC) if status in (JobStatus.SUCCEEDED, JobStatus.FAILED) else None,
        result={"final_response": "done"} if status == JobStatus.SUCCEEDED else None,
    )
    import asyncio

    asyncio.new_event_loop().run_until_complete(job_store.insert(run))
    return run


# ── signals ─────────────────────────────────────────────────


def test_signals_emit_happy_path() -> None:
    runtime, parts = _build_runtime()
    with _patch_session(signals, runtime):
        result = runner.invoke(
            signals.app,
            [
                "emit",
                "support.ticket.created",
                "--payload",
                '{"ticket_id":"T-42"}',
                "--source",
                "test",
                "--tenant",
                "t-1",
                "--config",
                "ignored",
            ],
        )
    assert result.exit_code == 0
    assert "signal_id=" in result.stdout
    assert "deduplicated=False" in result.stdout
    # Persisted under the right shape.
    stored = list(parts["signal_store"]._signals.values())
    assert len(stored) == 1
    assert stored[0].type == "support.ticket.created"
    assert stored[0].payload == {"ticket_id": "T-42"}
    assert stored[0].source == "test"


def test_signals_emit_with_identity_override() -> None:
    runtime, parts = _build_runtime()
    with _patch_session(signals, runtime):
        result = runner.invoke(
            signals.app,
            [
                "emit",
                "x",
                "--identity",
                '{"mode":"service_account","name":"bot"}',
                "--config",
                "ignored",
            ],
        )
    assert result.exit_code == 0
    sig = next(iter(parts["signal_store"]._signals.values()))
    assert sig.identity_claim == {"mode": "service_account", "name": "bot"}


def test_signals_emit_rejects_invalid_payload_json() -> None:
    runtime, _ = _build_runtime()
    with _patch_session(signals, runtime):
        result = runner.invoke(
            signals.app,
            ["emit", "x", "--payload", "not json", "--config", "ignored"],
        )
    assert result.exit_code != 0
    assert "Invalid JSON" in result.stdout


def test_signals_list_happy_path() -> None:
    runtime, parts = _build_runtime()
    sig = _seed_signal(parts["signal_store"])
    with _patch_session(signals, runtime):
        result = runner.invoke(signals.app, ["list", "--config", "ignored"])
    assert result.exit_code == 0
    assert str(sig.signal_id) in result.stdout
    assert "demo.event" in result.stdout or sig.type in result.stdout


def test_signals_list_empty() -> None:
    runtime, _ = _build_runtime()
    with _patch_session(signals, runtime):
        result = runner.invoke(signals.app, ["list", "--config", "ignored"])
    assert result.exit_code == 0
    assert "No signals" in result.stdout


def test_signals_show_happy_path() -> None:
    runtime, parts = _build_runtime()
    sig = _seed_signal(parts["signal_store"])
    with _patch_session(signals, runtime):
        result = runner.invoke(
            signals.app,
            ["show", str(sig.signal_id), "--config", "ignored"],
        )
    assert result.exit_code == 0
    assert str(sig.signal_id) in result.stdout
    assert "payload" in result.stdout


def test_signals_show_unknown_id() -> None:
    runtime, _ = _build_runtime()
    with _patch_session(signals, runtime):
        result = runner.invoke(
            signals.app,
            ["show", str(_uuid.uuid4()), "--config", "ignored"],
        )
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_signals_show_invalid_uuid() -> None:
    runtime, _ = _build_runtime()
    with _patch_session(signals, runtime):
        result = runner.invoke(signals.app, ["show", "not-a-uuid", "--config", "ignored"])
    assert result.exit_code == 1
    assert "Invalid signal id" in result.stdout


# ── jobs ────────────────────────────────────────────────────


def test_jobs_list_empty_registry() -> None:
    runtime, _ = _build_runtime()
    with _patch_session(jobs, runtime):
        result = runner.invoke(jobs.app, ["list", "--config", "ignored"])
    assert result.exit_code == 0
    assert "No triggers" in result.stdout


def test_jobs_list_with_trigger() -> None:
    runtime, parts = _build_runtime()

    class _T:
        @property
        def trigger_id(self) -> str:
            return "demo"

        @property
        def parallelism(self) -> str:
            return "per_user"

        @property
        def visibility(self) -> str:
            return "actor"

        @property
        def respect_chat_binding(self) -> bool:
            return False

        def matches(self, signal):  # pragma: no cover
            return False

        def build_job_spec(self, signal):  # pragma: no cover
            raise NotImplementedError

    parts["registry"].register(_T())
    with _patch_session(jobs, runtime):
        result = runner.invoke(jobs.app, ["list", "--config", "ignored"])
    assert result.exit_code == 0
    assert "demo" in result.stdout


def test_jobs_runs_unknown_trigger() -> None:
    runtime, _ = _build_runtime()
    with _patch_session(jobs, runtime):
        result = runner.invoke(jobs.app, ["runs", "no-such", "--config", "ignored"])
    assert result.exit_code == 1
    assert "not registered" in result.stdout


# ── runs ────────────────────────────────────────────────────


def test_runs_list_happy_path() -> None:
    runtime, parts = _build_runtime()
    run = _seed_run(parts["job_store"])
    with _patch_session(runs, runtime):
        result = runner.invoke(runs.app, ["list", "--config", "ignored"])
    assert result.exit_code == 0
    # The run_id appears in the first table column with ``no_wrap=True``,
    # so it survives Rich's adaptive truncation regardless of terminal
    # width.  Substring match on the leading 8 characters of the UUID
    # catches the row even when the second column is squashed.
    assert str(run.run_id)[:8] in result.stdout


def test_runs_list_empty() -> None:
    runtime, _ = _build_runtime()
    with _patch_session(runs, runtime):
        result = runner.invoke(runs.app, ["list", "--config", "ignored"])
    assert result.exit_code == 0
    assert "No runs" in result.stdout


def test_runs_show_happy_path() -> None:
    runtime, parts = _build_runtime()
    run = _seed_run(parts["job_store"])
    with _patch_session(runs, runtime):
        result = runner.invoke(runs.app, ["show", str(run.run_id), "--config", "ignored"])
    assert result.exit_code == 0
    assert str(run.run_id) in result.stdout
    assert "succeeded" in result.stdout
    assert "result" in result.stdout


def test_runs_show_unknown() -> None:
    runtime, _ = _build_runtime()
    with _patch_session(runs, runtime):
        result = runner.invoke(runs.app, ["show", str(_uuid.uuid4()), "--config", "ignored"])
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_runs_retry_re_enqueues() -> None:
    runtime, parts = _build_runtime()
    run = _seed_run(parts["job_store"])
    # Insert the originating signal so the queue has a referent —
    # in the in-memory queue this is informational only, but we
    # still check the queue gained a row.
    with _patch_session(runs, runtime):
        result = runner.invoke(runs.app, ["retry", str(run.run_id), "--config", "ignored"])
    assert result.exit_code == 0
    assert "requeued" in result.stdout
    assert parts["queue"].visible_messages == 1


def test_runs_cancel_terminal_runs_is_noop() -> None:
    runtime, parts = _build_runtime()
    run = _seed_run(parts["job_store"], status=JobStatus.SUCCEEDED)
    with _patch_session(runs, runtime):
        result = runner.invoke(runs.app, ["cancel", str(run.run_id), "--config", "ignored"])
    assert result.exit_code == 0
    assert "no-op" in result.stdout
    refreshed = parts["job_store"]._runs[run.run_id]
    assert refreshed.status == JobStatus.SUCCEEDED


def test_runs_cancel_pending_run() -> None:
    runtime, parts = _build_runtime()
    run = _seed_run(parts["job_store"], status=JobStatus.PENDING)
    with _patch_session(runs, runtime):
        result = runner.invoke(runs.app, ["cancel", str(run.run_id), "--config", "ignored"])
    assert result.exit_code == 0
    assert "cancelled" in result.stdout
    refreshed = parts["job_store"]._runs[run.run_id]
    assert refreshed.status == JobStatus.CANCELLED


# ── schedules ───────────────────────────────────────────────


def test_schedules_list_empty() -> None:
    runtime, _ = _build_runtime()
    with _patch_session(schedules, runtime):
        result = runner.invoke(schedules.app, ["list", "--config", "ignored"])
    assert result.exit_code == 0
    assert "No schedules" in result.stdout


def test_schedules_list_with_record() -> None:
    runtime, parts = _build_runtime()
    import asyncio

    asyncio.new_event_loop().run_until_complete(
        parts["schedule_store"].upsert(
            OrchidScheduleRecord(
                schedule_id="s1",
                trigger_id="t1",
                cron="0 7 * * *",
                interval_seconds=None,
                identity_claim={"mode": "service_account", "name": "bot"},
                last_fire_at=None,
                next_fire_at=None,
                enabled=True,
            )
        )
    )
    with _patch_session(schedules, runtime):
        result = runner.invoke(schedules.app, ["list", "--config", "ignored"])
    assert result.exit_code == 0
    assert "s1" in result.stdout


def test_schedules_show_unknown() -> None:
    runtime, _ = _build_runtime()
    with _patch_session(schedules, runtime):
        result = runner.invoke(schedules.app, ["show", "no-such", "--config", "ignored"])
    assert result.exit_code == 1
    assert "not found" in result.stdout


def test_schedules_disable_then_enable() -> None:
    runtime, parts = _build_runtime()
    import asyncio

    asyncio.new_event_loop().run_until_complete(
        parts["schedule_store"].upsert(
            OrchidScheduleRecord(
                schedule_id="s1",
                trigger_id="t1",
                cron="* * * * *",
                interval_seconds=None,
                identity_claim={"mode": "service_account", "name": "bot"},
                last_fire_at=None,
                next_fire_at=None,
                enabled=True,
            )
        )
    )

    with _patch_session(schedules, runtime):
        r1 = runner.invoke(schedules.app, ["disable", "s1", "--config", "ignored"])
    assert r1.exit_code == 0
    assert "disabled" in r1.stdout
    refreshed = parts["schedule_store"]._records["s1"]
    assert refreshed.enabled is False

    with _patch_session(schedules, runtime):
        r2 = runner.invoke(schedules.app, ["enable", "s1", "--config", "ignored"])
    assert r2.exit_code == 0
    assert "enabled" in r2.stdout
    refreshed = parts["schedule_store"]._records["s1"]
    assert refreshed.enabled is True


# ── _events_session disable guard ───────────────────────────


def test_events_session_raises_when_events_disabled() -> None:
    """If a YAML has ``events.enabled=false`` (the default), the
    session helper raises immediately rather than silently no-op."""
    from orchid_cli.commands._events_session import resolve_events_session

    fake_orchid = MagicMock()
    fake_orchid.config.events = None
    fake_orchid.close = AsyncMock()
    with patch("orchid_cli.commands._events_session.bootstrap", AsyncMock(return_value=fake_orchid)):
        import asyncio

        with pytest.raises(RuntimeError, match="events block disabled"):
            asyncio.new_event_loop().run_until_complete(resolve_events_session("ignored"))
    fake_orchid.close.assert_awaited_once()
