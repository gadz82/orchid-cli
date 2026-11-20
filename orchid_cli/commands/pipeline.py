"""``orchid pipeline`` — list, inspect, validate and run data pipelines.

Runs in-process through the Orchid facade (no HTTP), so the CLI is a peer to
``orchid-api`` rather than a client. No command creates a chat row or writes a
chat message. JSON output from ``run`` is the same body the API returns.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import types
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import typer
import yaml
from orchid_ai.config.loader import load_config
from orchid_ai.core.pipeline import (
    OrchidPipelineAuthError,
    OrchidPipelineConfigError,
    OrchidPipelineDisabledError,
    OrchidPipelineError,
    OrchidPipelineInputError,
    OrchidPipelineNotFoundError,
    OrchidPipelineShapeError,
    OrchidPipelineTimeoutError,
)
from orchid_ai.pipeline.registry import PipelineRegistry
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from ..auth.middleware import get_auth_context
from ..bootstrap import apply_cli_config, bootstrap

logger = logging.getLogger(__name__)

# ORCHID-MEM: 01a1f448-40ea-75e2-ab00-3e8728f2859f — Pipeline CLI; list/show/validate/run with JSON/YAML/stdin input, machine output and documented exit codes.
app = typer.Typer(
    name="pipeline",
    help="Data pipelines — list, inspect, validate and run.",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)

_OUTPUT_FORMATS = ("pretty", "json", "yaml")
_EXIT_INTERNAL = 1
_EXIT_VALIDATION = 2
_EXIT_FAILED = 3
_EXIT_TIMEOUT = 4
_EXIT_NOT_FOUND = 5


class _InputError(Exception):
    """Input parsing/validation failure (exit 2)."""


# ── Commands ────────────────────────────────────────────────


@app.command("list")
def list_command(
    as_json: bool = typer.Option(False, "--json", help="Machine-readable JSON."),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    """List configured pipelines."""
    asyncio.run(_list_async(config_path=config_path, as_json=as_json))


@app.command("show")
def show_command(
    name: str = typer.Argument(..., help="Pipeline name."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable JSON."),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    """Show one pipeline definition (sanitized)."""
    asyncio.run(_show_async(config_path=config_path, name=name, as_json=as_json))


@app.command("validate")
def validate_command(
    name: str = typer.Argument(..., help="Pipeline name."),
    input_path: str | None = typer.Option(None, "--input", "-i", help="Input JSON/YAML file, or '-' for stdin."),
    input_json: str | None = typer.Option(None, "--input-json", help="Inline JSON input."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable JSON."),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    """Validate pipeline input without running anything."""
    asyncio.run(
        _validate_async(
            config_path=config_path,
            name=name,
            input_path=input_path,
            input_json=input_json,
            as_json=as_json,
        )
    )


@app.command("run")
def run_command(
    name: str = typer.Argument(..., help="Pipeline name."),
    input_path: str | None = typer.Option(None, "--input", "-i", help="Input JSON/YAML file, or '-' for stdin."),
    input_json: str | None = typer.Option(None, "--input-json", help="Inline JSON input."),
    seed_path: str | None = typer.Option(None, "--seed", help="Seed JSON/YAML file (list of objects)."),
    output: str = typer.Option("pretty", "--output", "-o", help="pretty | json | yaml"),
    include_graph: bool = typer.Option(False, "--include-graph", help="Include the information graph."),
    graph_out: str | None = typer.Option(None, "--graph-out", help="Write the graph snapshot to this file."),
    timeout: float | None = typer.Option(None, "--timeout", help="Wall-clock timeout in seconds.", min=0.1),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Only print the summary."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Include job and graph detail."),
    config_path: str = typer.Option("orchid.yml", "--config", "-c", help="Path to orchid.yml."),
) -> None:
    """Run a pipeline synchronously and print its result."""
    fmt = _normalize_output(output)
    asyncio.run(
        _run_async(
            config_path=config_path,
            name=name,
            input_path=input_path,
            input_json=input_json,
            seed_path=seed_path,
            output=fmt,
            include_graph=include_graph,
            graph_out=graph_out,
            timeout=timeout,
            quiet=quiet,
            verbose=verbose,
        )
    )


@asynccontextmanager
async def _pipeline_context(config_path: str, *, warm: bool = False):
    """Bootstrap the facade; optionally resolve auth and warm MCP caches.

    ``list``/``show``/``validate`` never warm MCP or resolve a user: validation
    must make no model, tool or network call. ``run`` opts into the normal
    per-user warm-up so pipeline agent jobs see current capabilities.
    """
    if not warm:
        try:
            config = _load_pipeline_config(config_path)
            registry = PipelineRegistry.from_config(config.pipelines)
        except Exception as exc:
            _fail(f"Could not load pipeline configuration: {type(exc).__name__}: {exc}", _EXIT_VALIDATION, cause=exc)
        yield types.SimpleNamespace(pipelines=registry), None
        return

    orchid = None
    try:
        orchid = await bootstrap(config_path)
        auth = await get_auth_context(config_path)
        try:
            await orchid.session_warmer.warm_for_user(auth)
        except Exception as exc:
            logger.warning("[CLI] Per-user MCP warm-up raised: %s", exc)
        yield orchid, auth
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(f"Could not load configuration or authenticate: {type(exc).__name__}: {exc}", _EXIT_VALIDATION, cause=exc)
    finally:
        if orchid is not None:
            await orchid.close()


def _load_pipeline_config(config_path: str):
    """Resolve an ``orchid.yml`` root or a direct agents config without a runtime.

    ``apply_cli_config`` exports ``agents.config_path`` and the rest of the YAML
    to env; ``load_config`` then reads the referenced agents file. A direct
    ``agents.yaml`` has no indirection and is loaded as-is. Markdown roots use the
    framework's marker loader, which parses frontmatter without building MCP or
    opening storage.
    """
    path = Path(config_path)
    if path.suffix.lower() == ".md":
        from orchid_ai.config.md_loader import load_md_config

        config, _hashes = load_md_config(path)
        return config
    apply_cli_config(config_path)
    agents_path = os.environ.get("AGENTS_CONFIG_PATH", "")
    return load_config(agents_path or config_path)


# ── Async bodies ────────────────────────────────────────────


async def _list_async(*, config_path: str, as_json: bool) -> None:
    async with _pipeline_context(config_path) as (orchid, _auth):
        registry = orchid.pipelines
        if registry is None:
            _fail("No pipelines are configured or the block is disabled.", _EXIT_NOT_FOUND)
        infos = registry.list()
    if not infos:
        _fail("No pipelines are configured.", _EXIT_NOT_FOUND)
    payload = [_public_info(info, registry.get(info.name)) for info in infos]
    if as_json:
        typer.echo(json.dumps(payload, indent=2, default=str))
        return
    table = Table(title="Pipelines", show_lines=False)
    table.add_column("name", style="cyan")
    table.add_column("version", style="dim")
    table.add_column("jobs", justify="right")
    table.add_column("tool")
    table.add_column("async")
    table.add_column("description")
    for info, item in zip(infos, payload, strict=True):
        table.add_row(
            escape(info.name),
            escape(info.version),
            str(len(info.jobs)),
            "yes" if item["expose"]["as_tool"] else "",
            "yes" if item["async"]["enabled"] else "",
            escape(info.description),
        )
    console.print(table)


async def _show_async(*, config_path: str, name: str, as_json: bool) -> None:
    async with _pipeline_context(config_path) as (orchid, _auth):
        registry = _require_registry(orchid)
        definition = registry.get(name)
        info = registry.info(name)
    if definition is None or info is None:
        _fail(f"Pipeline {name!r} not found or disabled.", _EXIT_NOT_FOUND)
    payload = _public_info(info, definition)
    if as_json:
        typer.echo(json.dumps(payload, indent=2, default=str))
        return
    console.print(f"[bold]name[/bold]: {escape(info.name)}")
    console.print(f"[bold]version[/bold]: {escape(info.version)}")
    console.print(f"[bold]description[/bold]: {escape(info.description)}")
    console.print(f"[bold]expose.as_tool[/bold]: {payload['expose']['as_tool']}")
    if payload["expose"]["require_role"]:
        console.print(f"[bold]expose.require_role[/bold]: {escape(str(payload['expose']['require_role']))}")
    if payload["async"]["enabled"]:
        console.print(f"[bold]async.mode[/bold]: {payload['async']['mode']}")
    if info.input_schema is not None:
        console.print("\n[bold cyan]input schema[/bold cyan]:")
        console.print(json.dumps(info.input_schema, indent=2, default=str), markup=False, soft_wrap=True)
    if info.output_schema is not None:
        console.print("\n[bold cyan]output schema[/bold cyan]:")
        console.print(json.dumps(info.output_schema, indent=2, default=str), markup=False, soft_wrap=True)
    table = Table(title="Jobs")
    table.add_column("id", style="cyan")
    table.add_column("kind")
    table.add_column("depends_on", style="dim")
    for job in info.jobs:
        table.add_row(job.id, job.kind, ", ".join(job.depends_on))
    console.print(table)


async def _validate_async(
    *,
    config_path: str,
    name: str,
    input_path: str | None,
    input_json: str | None,
    as_json: bool,
) -> None:
    raw = _load_input(input_path, input_json)
    async with _pipeline_context(config_path) as (orchid, _auth):
        registry = _require_registry(orchid)
        definition = registry.get(name)
    if definition is None:
        _fail(f"Pipeline {name!r} not found or disabled.", _EXIT_NOT_FOUND)
    try:
        _prepare_input(definition, raw)
    except _InputError as exc:
        result = {"valid": False, "errors": _error_list(exc)}
        if as_json:
            typer.echo(json.dumps(result, indent=2, default=str))
        else:
            err_console.print(f"[red]✗[/red] Invalid input for pipeline {name!r}: {exc}")
        raise typer.Exit(code=_EXIT_VALIDATION) from exc
    result = {"valid": True, "errors": []}
    if as_json:
        typer.echo(json.dumps(result, indent=2, default=str))
    else:
        console.print(f"[green]✓[/green] Input is valid for pipeline {name!r}.")
    raise typer.Exit(code=0)


async def _run_async(
    *,
    config_path: str,
    name: str,
    input_path: str | None,
    input_json: str | None,
    seed_path: str | None,
    output: str,
    include_graph: bool,
    graph_out: str | None,
    timeout: float | None,
    quiet: bool,
    verbose: bool,
) -> None:
    raw = _load_input(input_path, input_json)
    seed = _load_seed(seed_path)
    async with _pipeline_context(config_path, warm=True) as (orchid, auth):
        registry = _require_registry(orchid)
        definition = registry.get(name)
        if definition is None:
            _fail(f"Pipeline {name!r} not found or disabled.", _EXIT_NOT_FOUND)
        try:
            prepared = _prepare_input(definition, raw)
        except _InputError as exc:
            _fail(f"Invalid input for pipeline {name!r}: {exc}", _EXIT_VALIDATION, cause=exc)
        want_graph = include_graph or graph_out is not None
        observer = _VerboseObserver() if verbose else None
        try:
            result = await orchid.run_pipeline(
                name,
                prepared,
                auth=auth,
                seed=seed,
                mode="direct",
                timeout=timeout,
                include_graph=want_graph,
                observer=observer,
            )
        except OrchidPipelineNotFoundError as exc:
            _fail(f"Pipeline {name!r} not found or disabled: {exc}", _EXIT_NOT_FOUND, cause=exc)
        except OrchidPipelineDisabledError as exc:
            _fail(f"Pipeline {name!r} is disabled: {exc}", _EXIT_NOT_FOUND, cause=exc)
        except (OrchidPipelineInputError, OrchidPipelineShapeError) as exc:
            _fail(f"Invalid input for pipeline {name!r}: {exc}", _EXIT_VALIDATION, cause=exc)
        except OrchidPipelineTimeoutError as exc:
            _fail(f"Pipeline {name!r} timed out: {exc}", _EXIT_TIMEOUT, cause=exc)
        except OrchidPipelineAuthError as exc:
            _fail(f"Pipeline {name!r} rejected the caller: {exc}", _EXIT_VALIDATION, cause=exc)
        except OrchidPipelineConfigError as exc:
            _fail(f"Pipeline {name!r} configuration is invalid: {exc}", _EXIT_VALIDATION, cause=exc)
        except OrchidPipelineError as exc:
            _fail(f"Pipeline {name!r} failed: {exc}", _EXIT_INTERNAL, cause=exc)
        except Exception as exc:
            logger.exception("pipeline run failed unexpectedly")
            _fail(f"Pipeline {name!r} failed unexpectedly ({type(exc).__name__}).", _EXIT_INTERNAL, cause=exc)

    omitted = (result.metadata or {}).get("graph_omitted") == "size"
    if want_graph and omitted:
        _fail("The graph was omitted because it exceeds the pipeline cap.", _EXIT_FAILED)
    print_payload = result.to_dict(include_graph=include_graph)
    if graph_out is not None:
        graph = result.graph or {}
        path = Path(graph_out).expanduser()
        try:
            path.write_text(json.dumps(graph, indent=2, default=str), encoding="utf-8")
        except OSError as exc:
            _fail(f"Could not write graph to {graph_out!r}: {exc}", _EXIT_VALIDATION, cause=exc)
        if output == "pretty" and not quiet:
            console.print(f"[green]✓[/green] graph written to {escape(str(path))}")

    if output == "json":
        typer.echo(json.dumps(print_payload, indent=2, default=str))
    elif output == "yaml":
        typer.echo(yaml.safe_dump(print_payload, sort_keys=False, allow_unicode=True))
    else:
        _print_pretty(result, print_payload, quiet=quiet, verbose=verbose)

    raise typer.Exit(code=_result_exit_code(result.status))


# ── Input and output helpers ────────────────────────────────


def _require_registry(orchid: Any) -> Any:
    registry = orchid.pipelines
    if registry is None:
        _fail("No pipelines are configured or the block is disabled.", _EXIT_NOT_FOUND)
    return registry


def _load_input(input_path: str | None, input_json: str | None) -> dict[str, Any]:
    if bool(input_path) == bool(input_json):
        _fail("Provide exactly one of --input or --input-json.", _EXIT_VALIDATION)
    if input_json is not None:
        try:
            value = json.loads(input_json)
        except json.JSONDecodeError as exc:
            _fail(f"--input-json is not valid JSON: {exc.msg}", _EXIT_VALIDATION, cause=exc)
    else:
        assert input_path is not None
        value = _read_document(input_path, label="--input")
    if not isinstance(value, dict):
        _fail("Pipeline input must be a JSON/YAML object.", _EXIT_VALIDATION)
    return value


def _load_seed(seed_path: str | None) -> list[dict[str, Any]]:
    if seed_path is None:
        return []
    value = _read_document(seed_path, label="--seed")
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        _fail("--seed must contain a list of objects.", _EXIT_VALIDATION)
    return value


def _read_document(path: str, *, label: str) -> Any:
    try:
        if path == "-":
            text = sys.stdin.read()
            return _parse_document(text, source="stdin")
        file_path = Path(path).expanduser()
        text = file_path.read_text(encoding="utf-8")
        if file_path.suffix.lower() in (".yaml", ".yml"):
            return yaml.safe_load(text)
        if file_path.suffix.lower() == ".json":
            return json.loads(text)
        return _parse_document(text, source=str(file_path))
    except _InputError as exc:
        _fail(str(exc), _EXIT_VALIDATION, cause=exc)
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        _fail(f"{label} could not be read: {exc}", _EXIT_VALIDATION, cause=exc)


def _parse_document(text: str, *, source: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise _InputError(f"{source} is not valid JSON or YAML: {exc}") from exc


def _prepare_input(definition: Any, raw: dict[str, Any]) -> dict[str, Any]:
    payload = dict(raw)
    input_config = getattr(definition.definition, "input", None)
    if input_config is not None:
        for key, value in getattr(input_config, "defaults", {}).items():
            payload.setdefault(key, value)
    shape = definition.input_shape
    if shape is None:
        return payload
    try:
        return shape.dump(payload, shape_version=shape.version)
    except OrchidPipelineShapeError as exc:
        raise _InputError(str(exc)) from exc


def _error_list(exc: _InputError) -> list[dict[str, str]]:
    cause = exc.__cause__
    errors = getattr(cause, "errors", None)
    if errors:
        return [dict(item) for item in errors]
    return [{"path": "", "type": "value_error", "message": str(exc)}]


def _public_info(info: Any, definition: Any | None = None) -> dict[str, Any]:
    expose = info.expose
    async_config = info.async_
    expose_config = definition.definition.expose if definition is not None else None

    def _exposed(key: str, default: Any = None) -> Any:
        if expose_config is not None:
            return getattr(expose_config, key, default)
        return expose.get(key, default)

    return {
        "name": info.name,
        "description": info.description,
        "version": info.version,
        "jobs": [job.to_dict() for job in info.jobs],
        "input_schema": info.input_schema,
        "output_schema": info.output_schema,
        "expose": {
            "as_tool": bool(_exposed("as_tool", False)),
            "requires_approval": bool(_exposed("requires_approval", False)),
            "parallel_safe": bool(_exposed("parallel_safe", False)),
            "require_role": _exposed("require_role"),
            "max_tool_result_chars": _exposed("max_tool_result_chars"),
            "interpretation": _exposed("interpretation"),
        },
        "async": {
            "enabled": bool(async_config.get("enabled")),
            "mode": async_config.get("mode"),
        },
    }


class _VerboseObserver:
    """Print pipeline job events to stderr when ``--verbose`` is set."""

    async def emit(self, event: Any) -> None:
        if event.type not in ("pipeline.job.started", "pipeline.job.finished"):
            return
        data = event.data or {}
        job = escape(str(data.get("job", "")))
        if event.type.endswith("started"):
            err_console.print(f"[dim]→ job {job} started[/dim]")
        else:
            status = escape(str(data.get("status", "")))
            err_console.print(f"[dim]← job {job} {status}[/dim]")


def _print_pretty(result: Any, payload: dict[str, Any], *, quiet: bool, verbose: bool) -> None:
    if quiet:
        summary = payload.get("summary") or payload.get("error") or payload.get("status", "")
        console.print(escape(str(summary)))
        return

    duration = _format_seconds(payload.get("duration_ms"))
    console.print(
        f"[bold]Pipeline:[/bold] {escape(str(payload.get('pipeline', '')))} "
        f"(run {escape(str(payload.get('run_id', '')))})"
    )
    status = escape(str(payload.get("status", "")))
    console.print(f"[bold]Status:[/bold]   {status}{f' ({duration})' if duration else ''}")
    if payload.get("summary"):
        console.print("\n[bold]Summary:[/bold]")
        for line in str(payload["summary"]).splitlines() or [""]:
            console.print(f"  {escape(line)}")
    if payload.get("error"):
        console.print(f"\n[bold red]Error:[/bold red] {escape(str(payload['error']))}")

    jobs = payload.get("jobs") or {}
    if jobs:
        console.print("\n[bold]Jobs:[/bold]")
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            mark = {"succeeded": "✓", "failed": "✗", "skipped": "-", "cancelled": "⊘"}.get(
                str(job.get("status", "")), "?"
            )
            color = (
                "green" if job.get("status") == "succeeded" else "red" if job.get("status") == "failed" else "yellow"
            )
            line = (
                f"  [{color}]{mark}[/{color}] {escape(str(job_id))}   "
                f"{escape(str(job.get('kind', '')))}   {_format_seconds(job.get('duration_ms'))}"
            )
            if job.get("reason"):
                line += f"   → {escape(str(job['reason']))}"
            if job.get("error"):
                line += f"   [red]{escape(str(job['error']))}[/red]"
            console.print(line)

    output = payload.get("output")
    if output is not None:
        console.print("\n[bold]Output:[/bold]")
        console.print(
            yaml.safe_dump(output, sort_keys=False, allow_unicode=True).rstrip(), markup=False, soft_wrap=True
        )

    graph = payload.get("graph")
    if graph:
        console.print("\n[bold]Graph:[/bold]")
        console.print(yaml.safe_dump(graph, sort_keys=False, allow_unicode=True).rstrip(), markup=False, soft_wrap=True)

    stats = payload.get("graph_stats")
    if stats and verbose:
        console.print(f"\n[bold]Graph stats:[/bold] {escape(json.dumps(stats, default=str))}")
    if verbose and payload.get("metadata"):
        console.print(f"[dim]metadata: {escape(json.dumps(payload['metadata'], default=str))}[/dim]")


def _format_seconds(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    if value >= 1000:
        return f"{value / 1000:.1f}s"
    return f"{value:.0f}ms"


def _format_duration(value: Any) -> str:
    return f"{value:.1f}" if isinstance(value, (int, float)) else ""


def _result_exit_code(status: str) -> int:
    if status == "succeeded":
        return 0
    if status in ("failed", "partial"):
        return _EXIT_FAILED
    if status in ("cancelled",):
        return _EXIT_TIMEOUT
    return _EXIT_INTERNAL


def _normalize_output(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in _OUTPUT_FORMATS:
        _fail(f"--output must be one of {', '.join(_OUTPUT_FORMATS)}.", _EXIT_VALIDATION)
    return normalized


def _fail(message: str, code: int, *, cause: BaseException | None = None) -> None:
    err_console.print(f"[red]✗[/red] {escape(message)}")
    raise typer.Exit(code=code) from cause
