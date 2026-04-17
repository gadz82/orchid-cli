"""
Slash-command registry — extensible handler set for the interactive REPL.

Integrators register custom commands in two ways:

1. **Explicit runtime call** — simplest for in-process use::

       from orchid_cli.slash_commands import register_slash_command

       async def my_handler(ctx: SlashContext) -> str | None:
           ctx.console.print(f"arg was {ctx.arg!r}")
           return None

       register_slash_command("/hello", my_handler, help="Say hi")

2. **Entry-point plugin** — declare in your package's ``pyproject.toml``::

       [project.entry-points."orchid_cli.slash_commands"]
       hello = "my_pkg.cli_slash:my_handler"

   Each entry must resolve to an ``async`` callable accepting a single
   :class:`SlashContext` argument.  The entry-point name is used as the
   slash-command name (e.g. ``hello`` → ``/hello``).

Handler contract
----------------
A slash-command handler is an async function::

    async def handler(ctx: SlashContext) -> str | None: ...

It returns the new ``chat_id`` when the command changes which chat the
REPL is pointing at (``/switch``, ``/new``), otherwise ``None``.

The handler receives everything it might reasonably need through the
:class:`SlashContext` — the graph context, the parsed argument string,
the active chat_id, the resolved :class:`AuthContext`, and a
``rich.console.Console`` for output.  New fields can be added in the
future without breaking existing handlers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


# ── Handler contract ──────────────────────────────────────────


@dataclass
class SlashContext:
    """Everything a slash-command handler might need, in one typed bag."""

    ctx: Any  # OrchidContext — not imported here to avoid a cycle
    arg: str
    current_chat_id: str
    auth: Any  # AuthContext — same reason
    console: Any  # rich.console.Console


# Return ``None`` when the command is informational (``/list``, ``/history``),
# or the new chat_id when the command rotates the active chat (``/switch``,
# ``/new``).  The REPL uses this return value to update its state.
SlashHandler = Callable[[SlashContext], Awaitable["str | None"]]


# ── Registry ─────────────────────────────────────────────────


@dataclass(frozen=True)
class SlashCommandEntry:
    """A registered slash command."""

    name: str
    handler: SlashHandler
    help: str = ""


_REGISTRY: dict[str, SlashCommandEntry] = {}


def register_slash_command(name: str, handler: SlashHandler, *, help: str = "") -> None:
    """Register (or replace) a slash command.

    ``name`` must start with ``/``; a leading slash is added automatically
    if omitted.  Overwrites any existing registration with the same name
    (last-wins) so integrators can override built-ins when they need to.
    """
    if not name.startswith("/"):
        name = f"/{name}"
    _REGISTRY[name] = SlashCommandEntry(name=name, handler=handler, help=help)
    logger.debug("[SlashCommands] Registered '%s'", name)


def unregister_slash_command(name: str) -> None:
    """Remove a slash command by name.  No-op if not registered."""
    if not name.startswith("/"):
        name = f"/{name}"
    _REGISTRY.pop(name, None)


def get_slash_command(name: str) -> SlashCommandEntry | None:
    """Return the entry for ``name``, or ``None`` if not registered."""
    if not name.startswith("/"):
        name = f"/{name}"
    return _REGISTRY.get(name)


def list_slash_commands() -> list[SlashCommandEntry]:
    """Return all registered commands, ordered alphabetically by name."""
    return sorted(_REGISTRY.values(), key=lambda e: e.name)


def clear_slash_commands() -> None:
    """Empty the registry — mainly useful for tests."""
    _REGISTRY.clear()


# ── Plugin discovery ────────────────────────────────────────


def load_slash_command_plugins() -> None:
    """Discover and register slash commands from the entry-point group.

    Consumer packages declare::

        [project.entry-points."orchid_cli.slash_commands"]
        mycmd = "mypackage.cli_slash:handler"

    Each entry must resolve to an async callable matching the
    :data:`SlashHandler` signature.  Individual failures are logged;
    see :func:`orchid_ai.plugins.iter_entry_point_plugins`.
    """
    from orchid_ai.plugins import iter_entry_point_plugins

    for name, handler in iter_entry_point_plugins("orchid_cli.slash_commands", logger=logger):
        if not callable(handler):
            logger.warning("[SlashCommands] Plugin '%s' is not callable — skipping", name)
            continue
        register_slash_command(name, handler)
        logger.info("[SlashCommands] Loaded plugin: /%s", name)
