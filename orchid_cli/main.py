"""
Orchid CLI — command-line interface for the Orchid agent framework.

Usage:
    orchid chat "What are LeBron's stats?" --config examples/basketball/orchid.yml
    orchid chat --interactive --config examples/basketball/orchid.yml
    orchid config validate examples/basketball/orchid.yml
    orchid index --config examples/basketball/orchid.yml

Plugin mechanism:
    Consumer packages can register additional CLI commands by declaring a
    ``[project.entry-points."orchid_cli.commands"]`` section in their
    ``pyproject.toml``.  Each entry must point to a ``typer.Typer`` instance::

        [project.entry-points."orchid_cli.commands"]
        mycommand = "mypackage.cli:app"

    The Typer app is automatically registered at startup under the entry name.
"""

from __future__ import annotations

import logging

import typer

from .commands import (
    auth,
    chat,
    config,
    external_agents,
    generate_flower,
    index,
    jobs,
    mcp,
    runs,
    schedules,
    signals,
)
from .slash_commands import load_slash_command_plugins

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="orchid",
    help="Orchid — multi-agent AI framework CLI",
    no_args_is_help=True,
)

# ── Built-in commands ──────────────────────────────────────────
app.add_typer(auth.app, name="auth")
app.add_typer(chat.app, name="chat")
app.add_typer(config.app, name="config")
app.add_typer(external_agents.app, name="external-agents")
app.add_typer(generate_flower.app, name="generate-flower")
app.add_typer(index.app, name="index")
app.add_typer(mcp.app, name="mcp")
# Pollen + Bloom (events) ops surface — local-only, mirrors orchid-api.
app.add_typer(signals.app, name="signals")
app.add_typer(jobs.app, name="jobs")
app.add_typer(runs.app, name="runs")
app.add_typer(schedules.app, name="schedules")


# ── Plugin discovery ───────────────────────────────────────────


def _load_plugins() -> None:
    """Discover and register CLI plugins from entry-point group ``orchid_cli.commands``.

    Each entry must resolve to a ``typer.Typer`` instance.  Individual
    failures are logged and skipped; see
    :func:`orchid_ai.plugins.iter_entry_point_plugins`.
    """
    from orchid_ai.plugins import iter_entry_point_plugins

    for name, plugin_app in iter_entry_point_plugins("orchid_cli.commands", logger=logger):
        if isinstance(plugin_app, typer.Typer):
            app.add_typer(plugin_app, name=name)
            logger.info("[CLI] Loaded plugin command: %s", name)
        else:
            logger.warning("[CLI] Plugin '%s' is not a Typer app — skipping", name)


_load_plugins()
load_slash_command_plugins()


if __name__ == "__main__":
    app()
