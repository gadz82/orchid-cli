"""
CLI bootstrapping — thin adapter over :class:`orchid_ai.Orchid`.

All heavy wiring (reader, chat storage, MCP token store, checkpointer,
runtime, graph) lives inside :class:`Orchid` so all three entry points
(``orchid-cli``, ``orchid-api``, in-process integrators) stay in
lock-step.  This module adds only CLI-specific concerns: the SQLite
default DSN, a YAML section to skip, and an async context manager for
clean shutdown.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from orchid_ai import Orchid

logger = logging.getLogger(__name__)


# Public defaults — referenced by command modules (e.g. mcp, auth) that
# want to honour the CLI's SQLite-first convention.
DEFAULT_STORAGE_CLASS = "orchid_ai.persistence.sqlite.OrchidSQLiteChatStorage"
DEFAULT_STORAGE_DSN = "~/.orchid/chats.db"
DEFAULT_TOKEN_STORE_CLASS = "orchid_ai.persistence.mcp_token_sqlite.OrchidSQLiteMCPTokenStore"


def apply_cli_config(config_path: str) -> None:
    """Apply ``orchid.yml`` values to env vars, honouring the CLI's
    ``skip_sections={"storage"}`` convention.

    Call this explicitly at command entry points (before :func:`bootstrap`)
    to make env-var mutation an obvious, visible step.  :func:`bootstrap`
    still calls it internally — a second call is idempotent because
    :func:`apply_yaml_to_env` only sets vars that are not already present.
    """
    from orchid_ai.config.yaml_env import apply_yaml_to_env

    apply_yaml_to_env(config_path, skip_sections={"storage"})


async def bootstrap(
    config_path: str,
    *,
    model: str = "",
    vector_backend: str = "",
    qdrant_url: str = "",
    embedding_model: str = "",
    chat_storage_class: str = "",
    chat_db_dsn: str = "",
    chat_extra_migrations_package: str | None = None,
) -> Orchid:
    """Build an :class:`Orchid` instance with CLI-friendly defaults.

    The CLI's SQLite-first defaults (``~/.orchid/chats.db``) win over
    any ``storage:`` block in ``orchid.yml``; the CLI is typically run
    outside Docker where the YAML's container paths would be wrong.

    ``chat_extra_migrations_package`` forwards an integrator-supplied
    migrations package to :class:`Orchid`.  When left ``None`` the
    value is picked up from the ``CHAT_EXTRA_MIGRATIONS_PACKAGE`` env
    var.

    Returns the fully-started :class:`Orchid` facade.  Pair with
    :meth:`Orchid.close` (or use :func:`cli_context`) to ensure
    aiosqlite / checkpointer / token-store connections are released
    before the event loop exits.
    """
    # CLI convention: storage block in YAML does NOT override our SQLite
    # default.  Everything else in YAML → env propagates as usual.
    orchid = await Orchid.from_config_path(
        config_path=config_path,
        apply_yaml=bool(config_path),
        skip_yaml_sections={"storage"},
        model=model,
        vector_backend=vector_backend,
        qdrant_url=qdrant_url,
        embedding_model=embedding_model,
        chat_storage_class=chat_storage_class,
        chat_db_dsn=chat_db_dsn,
        chat_extra_migrations_package=chat_extra_migrations_package,
    )

    logger.info(
        "[CLI] Ready — model=%s, agents=%s",
        orchid.runtime.default_model,
        list(orchid.config.agents.keys()),
    )
    return orchid


@asynccontextmanager
async def cli_context(config_path: str, *, model: str = ""):
    """Bootstrap and ensure clean shutdown (closes aiosqlite before event loop exits)."""
    orchid = await bootstrap(config_path, model=model)
    try:
        yield orchid
    finally:
        await orchid.close()
