"""
CLI bootstrapping — thin adapter over :func:`orchid_ai.bootstrap.build_runtime`.

All heavy wiring (reader, chat storage, MCP token store, checkpointer,
runtime) lives in the shared library function so the three entry points
(orchid-cli, orchid-api, ``OrchidClient``) stay in lock-step.  This module
adds only CLI-specific concerns: an :class:`OrchidContext` dataclass and
an async context manager for clean shutdown.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from orchid_ai.bootstrap import BootstrapResult, build_runtime, teardown_runtime
from orchid_ai.config.schema import AgentsConfig
from orchid_ai.core.mcp import MCPTokenStore
from orchid_ai.core.repository import VectorReader
from orchid_ai.graph.graph import build_graph
from orchid_ai.persistence.base import ChatStorage
from orchid_ai.runtime import OrchidRuntime

logger = logging.getLogger(__name__)


# Public defaults — referenced by command modules (e.g. mcp, auth) that
# want to honour the CLI's SQLite-first convention.
DEFAULT_STORAGE_CLASS = "orchid_ai.persistence.sqlite.SQLiteChatStorage"
DEFAULT_STORAGE_DSN = "~/.orchid/chats.db"
DEFAULT_TOKEN_STORE_CLASS = "orchid_ai.persistence.mcp_token_sqlite.SQLiteMCPTokenStore"


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


@dataclass
class OrchidContext:
    """Runtime context for CLI operations.

    Pair :func:`bootstrap` with :meth:`release_resources` (or use the
    :func:`cli_context` async context manager, which does it for you)
    to ensure aiosqlite / checkpointer / token-store connections are
    closed cleanly before the event loop exits.
    """

    graph: Any
    reader: VectorReader
    chat_repo: ChatStorage
    config: AgentsConfig
    model: str
    mcp_token_store: MCPTokenStore | None = None
    runtime: OrchidRuntime = field(default_factory=OrchidRuntime)
    # Private handle on the library-level ``BootstrapResult`` used by
    # :meth:`release_resources`.  Not part of the public API.
    _bootstrap: BootstrapResult | None = None

    async def release_resources(self) -> None:
        """Release every library-level resource this context holds.

        Idempotent: safe to call twice; the underlying ``BootstrapResult``
        is cleared after the first call so subsequent invocations are
        no-ops.  Typically called from :func:`cli_context` on context
        exit — explicit callers of :func:`bootstrap` must invoke this
        themselves.
        """
        if self._bootstrap is not None:
            await teardown_runtime(self._bootstrap)
            self._bootstrap = None


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
) -> OrchidContext:
    """Load config, build reader, build graph — return a ready-to-use context.

    The CLI's SQLite-first defaults (``~/.orchid/chats.db``) win over any
    ``storage:`` block in ``orchid.yml``; the CLI is typically run outside
    Docker where the YAML's container paths would be wrong.

    ``chat_extra_migrations_package`` forwards an integrator-supplied
    migrations package to the shared ``build_runtime``.  When left
    ``None`` the value is picked up from the ``CHAT_EXTRA_MIGRATIONS_PACKAGE``
    env var.
    """
    # CLI convention: storage block in YAML does NOT override our SQLite
    # default.  Everything else in YAML → env propagates as usual.
    result = await build_runtime(
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

    graph = build_graph(config=result.config, runtime=result.runtime)

    logger.info(
        "[CLI] Ready — model=%s, backend=%s, agents=%s",
        result.runtime.default_model,
        os.environ.get("VECTOR_BACKEND", "qdrant"),
        list(result.config.agents.keys()),
    )

    return OrchidContext(
        graph=graph,
        reader=result.runtime.get_reader(),
        chat_repo=result.chat_repo,
        config=result.config,
        model=result.runtime.default_model,
        mcp_token_store=result.mcp_token_store,
        runtime=result.runtime,
        _bootstrap=result,
    )


@asynccontextmanager
async def cli_context(config_path: str, *, model: str = ""):
    """Bootstrap and ensure clean shutdown (closes aiosqlite before event loop exits)."""
    ctx = await bootstrap(config_path, model=model)
    try:
        yield ctx
    finally:
        await ctx.release_resources()
