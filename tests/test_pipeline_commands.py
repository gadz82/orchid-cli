"""Tests for ``orchid pipeline`` commands, output modes and exit codes."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from orchid_ai.config.schema_pipeline import OrchidPipelinesConfig
from orchid_ai.core.pipeline import (
    OrchidPipelineConfigError,
    OrchidPipelineDisabledError,
    OrchidPipelineNotFoundError,
    OrchidPipelineResult,
    OrchidPipelineTimeoutError,
)
from orchid_ai.core.state import OrchidAuthContext
from orchid_ai.pipeline.registry import PipelineRegistry
from typer.testing import CliRunner

from orchid_cli.commands import pipeline

runner = CliRunner()


@pytest.fixture
def p017_steps(monkeypatch: pytest.MonkeyPatch) -> str:
    module = types.ModuleType("p017_steps")

    def load(ctx):
        return {"ok": True}

    module.load = load  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "p017_steps", module)
    return "p017_steps"


def _registry() -> PipelineRegistry:
    config = OrchidPipelinesConfig.model_validate(
        {
            "enabled": True,
            "definitions": {
                "demo": {
                    "description": "Demo pipeline",
                    "input": {"fields": {"account_id": {"type": "string", "required": True}}},
                    "jobs": {"load": {"kind": "deterministic", "uses": "p017_steps.load"}},
                    "expose": {"as_tool": True, "description": "Run demo"},
                },
                "beta": {
                    "description": "Beta pipeline",
                    "jobs": {"load": {"kind": "deterministic", "uses": "p017_steps.load"}},
                },
            },
        }
    )
    return PipelineRegistry.from_config(config)


def _auth() -> OrchidAuthContext:
    return OrchidAuthContext(access_token="t", tenant_key="t1", user_id="u1")


def _result(**overrides) -> OrchidPipelineResult:
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "run_id": "run-1",
        "pipeline": "demo",
        "status": "succeeded",
        "summary": "All good.",
        "output": {"ok": True},
        "graph": {"objects": [{"id": "o1"}]},
        "graph_stats": {"objects": 1},
        "jobs": {"load": {"status": "succeeded", "duration_ms": 10.0}},
        "started_at": now,
        "finished_at": now,
        "metadata": {},
    }
    values.update(overrides)
    return OrchidPipelineResult(**values)


class _FakeOrchid:
    def __init__(self, registry: Any, *, result: Any = None, error: Exception | None = None) -> None:
        self.pipelines = registry
        self.result = result or _result()
        self.error = error
        self.run_calls: list[dict[str, Any]] = []
        self.chat_repo = AsyncMock()

    async def run_pipeline(self, name, input, **kwargs):
        self.run_calls.append({"name": name, "input": input, **kwargs})
        if self.error is not None:
            raise self.error
        return self.result


def _session(orchid: Any):
    @asynccontextmanager
    async def _fake(config_path: str, *, warm: bool = False, **kwargs):
        yield orchid, _auth() if warm else None

    return _fake


def _invoke(orchid: Any, args: list[str], **kwargs):
    with patch.object(pipeline, "_pipeline_context", _session(orchid)):
        return runner.invoke(pipeline.app, [*args, "--config", "ignored"], **kwargs)


# ── list / show ─────────────────────────────────────────────


def test_list_pretty_and_json(p017_steps: str) -> None:
    orchid = _FakeOrchid(_registry())
    pretty = _invoke(orchid, ["list"])
    assert pretty.exit_code == 0
    assert "demo" in pretty.output
    assert "beta" in pretty.output

    machine = _invoke(orchid, ["list", "--json"])
    assert machine.exit_code == 0
    payload = json.loads(machine.stdout)
    assert [item["name"] for item in payload] == ["demo", "beta"]
    assert payload[0]["expose"]["as_tool"] is True
    assert "tool_name" not in machine.stdout


def test_list_without_pipelines_is_exit_5() -> None:
    orchid = _FakeOrchid(None)
    result = _invoke(orchid, ["list"])
    assert result.exit_code == 5
    assert "No pipelines" in result.output


def test_show_pretty_and_json(p017_steps: str) -> None:
    orchid = _FakeOrchid(_registry())
    pretty = _invoke(orchid, ["show", "demo"])
    assert pretty.exit_code == 0
    assert "Demo pipeline" in pretty.output
    assert "input schema" in pretty.output

    machine = _invoke(orchid, ["show", "demo", "--json"])
    payload = json.loads(machine.stdout)
    assert payload["name"] == "demo"
    assert payload["jobs"] == [{"id": "load", "kind": "deterministic", "depends_on": []}]


def test_show_unknown_is_exit_5(p017_steps: str) -> None:
    result = _invoke(_FakeOrchid(_registry()), ["show", "missing"])
    assert result.exit_code == 5
    assert "not found" in result.output


# ── validate ───────────────────────────────────────────────


def test_validate_valid_json_and_yaml_and_stdin(p017_steps: str, tmp_path: Path) -> None:
    orchid = _FakeOrchid(_registry())
    inline = _invoke(orchid, ["validate", "demo", "--input-json", '{"account_id":"a1"}'])
    assert inline.exit_code == 0
    assert "valid" in inline.output.lower()

    json_file = tmp_path / "input.json"
    json_file.write_text(json.dumps({"account_id": "a1"}), encoding="utf-8")
    from_file = _invoke(orchid, ["validate", "demo", "--input", str(json_file)])
    assert from_file.exit_code == 0

    yaml_file = tmp_path / "input.yaml"
    yaml_file.write_text("account_id: a1\n", encoding="utf-8")
    from_yaml = _invoke(orchid, ["validate", "demo", "--input", str(yaml_file)])
    assert from_yaml.exit_code == 0

    from_stdin = _invoke(orchid, ["validate", "demo", "--input", "-"], input='{"account_id":"a1"}')
    assert from_stdin.exit_code == 0
    assert orchid.run_calls == []


def test_validate_invalid_input_is_exit_2(p017_steps: str) -> None:
    orchid = _FakeOrchid(_registry())
    result = _invoke(orchid, ["validate", "demo", "--input-json", "{}"])
    assert result.exit_code == 2
    assert "Invalid input" in result.output
    assert orchid.run_calls == []

    machine = _invoke(orchid, ["validate", "demo", "--input-json", "{}", "--json"])
    assert machine.exit_code == 2
    payload = json.loads(machine.stdout)
    assert payload["valid"] is False
    assert payload["errors"]


def test_validate_argument_errors_are_exit_2(p017_steps: str) -> None:
    orchid = _FakeOrchid(_registry())
    assert _invoke(orchid, ["validate", "demo"]).exit_code == 2
    assert (
        _invoke(
            orchid,
            ["validate", "demo", "--input-json", "{}", "--input", "-"],
        ).exit_code
        == 2
    )
    assert _invoke(orchid, ["validate", "missing", "--input-json", "{}"]).exit_code == 5


# ── run ────────────────────────────────────────────────────


def test_run_json_matches_the_facade_result(p017_steps: str) -> None:
    orchid = _FakeOrchid(_registry())
    result = _invoke(
        orchid,
        ["run", "demo", "--input-json", '{"account_id":"a1"}', "--output", "json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "succeeded"
    assert payload["summary"] == "All good."
    assert payload["output"] == {"ok": True}
    assert "graph" not in payload
    [call] = orchid.run_calls
    assert call["mode"] == "direct"
    assert call["seed"] == []
    assert call["include_graph"] is False
    orchid.chat_repo.add_message.assert_not_called()
    orchid.chat_repo.create_chat.assert_not_called()


def test_run_yaml_seed_and_stdin(p017_steps: str, tmp_path: Path) -> None:
    orchid = _FakeOrchid(_registry())
    input_file = tmp_path / "input.yaml"
    input_file.write_text("account_id: a1\n", encoding="utf-8")
    seed_file = tmp_path / "seed.json"
    seed_file.write_text(json.dumps([{"id": "seed-1"}]), encoding="utf-8")

    result = _invoke(
        orchid,
        [
            "run",
            "demo",
            "--input",
            str(input_file),
            "--seed",
            str(seed_file),
            "--output",
            "yaml",
        ],
    )
    assert result.exit_code == 0
    payload = yaml.safe_load(result.stdout)
    assert payload["status"] == "succeeded"
    assert orchid.run_calls[0]["seed"] == [{"id": "seed-1"}]

    stdin = _invoke(
        orchid,
        ["run", "demo", "--input", "-", "--output", "json"],
        input='{"account_id":"stdin"}',
    )
    assert stdin.exit_code == 0
    assert orchid.run_calls[1]["input"] == {"account_id": "stdin"}


def test_run_pretty_quiet_and_verbose(p017_steps: str) -> None:
    orchid = _FakeOrchid(_registry(), result=_result(metadata={"trace": "x"}))
    pretty = _invoke(orchid, ["run", "demo", "--input-json", '{"account_id":"a1"}'])
    assert pretty.exit_code == 0
    assert "Pipeline:" in pretty.output
    assert "Status:" in pretty.output
    assert "Summary:" in pretty.output
    assert "Jobs:" in pretty.output
    assert "Graph stats:" not in pretty.output

    quiet = _invoke(orchid, ["run", "demo", "--input-json", '{"account_id":"a1"}', "--quiet"])
    assert quiet.exit_code == 0
    assert quiet.stdout.strip() == "All good."

    verbose = _invoke(orchid, ["run", "demo", "--input-json", '{"account_id":"a1"}', "--verbose"])
    assert verbose.exit_code == 0
    assert "metadata" in verbose.output
    assert "Graph stats:" in verbose.output


def test_run_include_graph_and_graph_out(p017_steps: str, tmp_path: Path) -> None:
    orchid = _FakeOrchid(_registry())
    graph_file = tmp_path / "graph.json"
    result = _invoke(
        orchid,
        [
            "run",
            "demo",
            "--input-json",
            '{"account_id":"a1"}',
            "--output",
            "json",
            "--graph-out",
            str(graph_file),
        ],
    )
    assert result.exit_code == 0
    assert json.loads(graph_file.read_text(encoding="utf-8")) == {"objects": [{"id": "o1"}]}
    assert orchid.run_calls[0]["include_graph"] is True
    assert "graph" not in json.loads(result.stdout)

    embedded = _invoke(
        orchid,
        ["run", "demo", "--input-json", '{"account_id":"a1"}', "--output", "json", "--include-graph"],
    )
    assert json.loads(embedded.stdout)["graph"] == {"objects": [{"id": "o1"}]}


def test_run_graph_omitted_is_exit_3(p017_steps: str, tmp_path: Path) -> None:
    orchid = _FakeOrchid(_registry(), result=_result(graph={}, metadata={"graph_omitted": "size"}))
    result = _invoke(
        orchid,
        [
            "run",
            "demo",
            "--input-json",
            '{"account_id":"a1"}',
            "--graph-out",
            str(tmp_path / "graph.json"),
        ],
    )
    assert result.exit_code == 3
    assert "omitted" in result.output


@pytest.mark.parametrize(
    ("status", "code"),
    [("failed", 3), ("partial", 3), ("cancelled", 4)],
)
def test_run_non_success_statuses(p017_steps: str, status: str, code: int) -> None:
    orchid = _FakeOrchid(_registry(), result=_result(status=status, output=None, summary=""))
    result = _invoke(orchid, ["run", "demo", "--input-json", '{"account_id":"a1"}'])
    assert result.exit_code == code


def test_run_exception_exit_codes(p017_steps: str) -> None:
    mapping = [
        (OrchidPipelineTimeoutError("deadline"), 4),
        (OrchidPipelineNotFoundError("missing"), 5),
        (OrchidPipelineDisabledError("disabled"), 5),
        (OrchidPipelineConfigError("bad config"), 2),
        (RuntimeError("boom"), 1),
    ]
    for error, code in mapping:
        orchid = _FakeOrchid(_registry(), error=error)
        result = _invoke(orchid, ["run", "demo", "--input-json", '{"account_id":"a1"}'])
        assert result.exit_code == code, (error, result.output)


def test_run_invalid_input_does_not_call_the_facade(p017_steps: str) -> None:
    orchid = _FakeOrchid(_registry())
    result = _invoke(orchid, ["run", "demo", "--input-json", "{}"])
    assert result.exit_code == 2
    assert orchid.run_calls == []


def test_run_machine_output_preserves_long_and_markup_text(p017_steps: str) -> None:
    orchid = _FakeOrchid(
        _registry(),
        result=_result(summary="[bold] keep me [/bold] " + "x" * 500),
    )
    result = _invoke(orchid, ["run", "demo", "--input-json", '{"account_id":"a1"}', "--output", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["summary"].startswith("[bold] keep me [/bold]")
    assert len(payload["summary"]) > 500


def test_list_machine_output_preserves_markup_text(p017_steps: str) -> None:
    orchid = _FakeOrchid(_registry())
    result = _invoke(orchid, ["list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload


def test_run_pretty_include_graph_prints_the_graph(p017_steps: str) -> None:
    orchid = _FakeOrchid(_registry())
    result = _invoke(
        orchid,
        ["run", "demo", "--input-json", '{"account_id":"a1"}', "--include-graph"],
    )
    assert result.exit_code == 0
    assert "Graph:" in result.output


def test_run_include_graph_cap_is_exit_3(p017_steps: str) -> None:
    orchid = _FakeOrchid(_registry(), result=_result(graph={}, metadata={"graph_omitted": "size"}))
    result = _invoke(
        orchid,
        ["run", "demo", "--input-json", '{"account_id":"a1"}', "--include-graph"],
    )
    assert result.exit_code == 3
    assert "omitted" in result.output


async def test_verbose_observer_prints_job_events(p017_steps: str, capsys: pytest.CaptureFixture[str]) -> None:
    from orchid_ai.core.pipeline import OrchidPipelineEvent

    observer = pipeline._VerboseObserver()
    await observer.emit(
        OrchidPipelineEvent(
            type="pipeline.job.started",
            run_id="run-1",
            timestamp=datetime.now(UTC),
            data={"job": "load"},
        )
    )
    captured = capsys.readouterr()
    assert "job load started" in captured.err


async def test_readonly_context_does_not_bootstrap_or_resolve_auth(p017_steps: str) -> None:
    from orchid_ai.config.schema_pipeline import OrchidPipelinesConfig

    config = OrchidPipelinesConfig.model_validate(
        {
            "enabled": True,
            "definitions": {
                "demo": {
                    "description": "Demo pipeline",
                    "jobs": {"load": {"kind": "deterministic", "uses": "p017_steps.load"}},
                }
            },
        }
    )

    async def _boom(*args, **kwargs):
        raise AssertionError("read-only commands must not bootstrap or resolve auth")

    with (
        patch.object(pipeline, "load_config", return_value=types.SimpleNamespace(pipelines=config)),
        patch.object(pipeline, "bootstrap", side_effect=_boom),
        patch.object(pipeline, "get_auth_context", side_effect=_boom),
    ):
        async with pipeline._pipeline_context("ignored") as (facade, auth):
            assert facade.pipelines.names() == ("demo",)
            assert auth is None


def test_malformed_config_is_exit_2() -> None:
    with patch.object(pipeline, "load_config", side_effect=ValueError("bad config")):
        result = runner.invoke(pipeline.app, ["list", "--config", "bad.yml"])
    assert result.exit_code == 2
    assert "Could not load pipeline configuration" in result.output


def test_show_with_markup_like_name_does_not_crash(p017_steps: str) -> None:
    result = _invoke(_FakeOrchid(_registry()), ["show", "[/bold]"])
    assert result.exit_code == 5
    assert "not found" in result.output


def test_run_invalid_output_mode_is_exit_2(p017_steps: str) -> None:
    orchid = _FakeOrchid(_registry())
    result = _invoke(orchid, ["run", "demo", "--input-json", '{"account_id":"a1"}', "--output", "xml"])
    assert result.exit_code == 2
    assert orchid.run_calls == []


# ── events session wiring ──────────────────────────────────


def test_events_session_passes_pipelines_and_runner(p017_steps: str) -> None:
    from orchid_ai.events.bootstrap import EventsRuntime

    from orchid_cli.commands import _events_session

    registry = _registry()
    orchid = MagicMock()
    orchid.pipelines = registry
    orchid.config.events = types.SimpleNamespace(enabled=True)
    orchid.config.agents = {}
    orchid.chat_repo = MagicMock()
    orchid.session_warmer = MagicMock()
    orchid.close = AsyncMock()
    runtime = EventsRuntime(enabled=True, producers=[])

    with (
        patch.object(_events_session, "bootstrap", AsyncMock(return_value=orchid)),
        patch.object(_events_session, "start_events", AsyncMock(return_value=runtime)) as start,
    ):
        resolved_orchid, resolved_runtime = asyncio.run(_events_session.resolve_events_session("ignored"))

    assert resolved_orchid is orchid
    assert resolved_runtime is runtime
    kwargs = start.await_args.kwargs
    assert kwargs["known_pipelines"] == {"demo", "beta"}
    assert isinstance(kwargs["pipeline_runner"], _events_session._CLIPipelineRunner)


async def test_cli_pipeline_runner_maps_bloom_to_chat(p017_steps: str) -> None:
    from orchid_cli.commands import _events_session

    orchid = MagicMock()
    orchid.run_pipeline = AsyncMock(return_value=_result())
    adapter = _events_session._CLIPipelineRunner(orchid)

    await adapter.run(
        "demo",
        {"account_id": "a1"},
        auth=_auth(),
        mode="bloom",
        chat_id="c-1",
        correlation_id="corr",
        include_graph=True,
    )

    orchid.run_pipeline.assert_awaited_once()
    kwargs = orchid.run_pipeline.await_args.kwargs
    assert kwargs["mode"] == "chat"
    assert kwargs["chat_id"] == "c-1"
    assert kwargs["correlation_id"] == "corr"
    assert kwargs["include_graph"] is True


def test_readonly_commands_resolve_orchid_yml_indirection(p017_steps: str, tmp_path: Path) -> None:
    agents_path = tmp_path / "agents.yaml"
    agents_path.write_text(
        yaml.safe_dump(
            {
                "version": "1",
                "pipelines": {
                    "enabled": True,
                    "definitions": {
                        "demo": {
                            "description": "Demo pipeline",
                            "jobs": {"load": {"kind": "deterministic", "uses": "p017_steps.load"}},
                        }
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    root = tmp_path / "orchid.yml"
    root.write_text(
        yaml.safe_dump({"agents": {"config_path": str(agents_path)}}, sort_keys=False),
        encoding="utf-8",
    )

    result = runner.invoke(pipeline.app, ["list", "--json", "--config", str(root)])

    assert result.exit_code == 0, result.output
    assert [item["name"] for item in json.loads(result.stdout)] == ["demo"]
