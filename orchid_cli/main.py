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

from .commands import auth, chat, config, index, mcp, skill

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
app.add_typer(index.app, name="index")
app.add_typer(mcp.app, name="mcp")
app.add_typer(skill.app, name="skill")


# ── Plugin discovery ───────────────────────────────────────────


def _load_plugins() -> None:
    """Discover and register CLI plugins from entry-point group ``orchid_cli.commands``."""
    try:
        from importlib.metadata import entry_points

        eps = entry_points()
        # Python 3.12+: eps.select(); 3.9-3.11: eps.get()
        plugins = (
            eps.select(group="orchid_cli.commands") if hasattr(eps, "select") else eps.get("orchid_cli.commands", [])
        )

        for ep in plugins:
            try:
                plugin_app = ep.load()
                if isinstance(plugin_app, typer.Typer):
                    app.add_typer(plugin_app, name=ep.name)
                    logger.info("[CLI] Loaded plugin command: %s", ep.name)
                else:
                    logger.warning("[CLI] Plugin '%s' is not a Typer app — skipping", ep.name)
            except Exception as exc:
                logger.warning("[CLI] Failed to load plugin '%s': %s", ep.name, exc)
    except Exception:
        pass  # importlib.metadata not available or no plugins — that's fine


_load_plugins()


if __name__ == "__main__":
    app()
