"""
Shared bootstrapping — load config, build graph, initialize persistence.

Mirrors the lifespan logic from orchid-api but without FastAPI.
SQLite storage is always initialized by default (no external DB required).
MCP token storage shares the same SQLite database as chat persistence.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from orchid_ai.config.loader import load_config
from orchid_ai.config.schema import AgentsConfig
from orchid_ai.core.mcp import MCPTokenStore
from orchid_ai.core.repository import VectorReader, VectorStoreAdmin
from orchid_ai.graph.graph import build_graph
from orchid_ai.persistence.base import ChatStorage
from orchid_ai.persistence.factory import build_chat_storage
from orchid_ai.persistence.mcp_token_factory import build_mcp_token_store
from orchid_ai.rag.factory import build_reader
from orchid_ai.runtime import OrchidRuntime

logger = logging.getLogger(__name__)


def _apply_yaml_to_env(config_path: str) -> None:
    """Parse orchid.yml and export values as env vars (if not already set).

    Storage settings (class, dsn) are skipped — the CLI has its own
    defaults (SQLite at ~/.orchid/chats.db) that are more appropriate
    than Docker-oriented paths often found in orchid.yml.
    """
    from orchid_ai.config.yaml_env import apply_yaml_to_env

    apply_yaml_to_env(config_path, skip_sections={"storage"})


# Defaults — SQLite storage ships with orchid, no external DB needed
DEFAULT_STORAGE_CLASS = "orchid_ai.persistence.sqlite.SQLiteChatStorage"
DEFAULT_STORAGE_DSN = "~/.orchid/chats.db"


DEFAULT_TOKEN_STORE_CLASS = "orchid_ai.persistence.mcp_token_sqlite.SQLiteMCPTokenStore"


@dataclass
class OrchidContext:
    """Runtime context for CLI operations."""

    graph: Any
    reader: VectorReader
    chat_repo: ChatStorage
    config: AgentsConfig
    model: str
    mcp_token_store: MCPTokenStore | None = None
    runtime: OrchidRuntime = field(default_factory=OrchidRuntime)


async def bootstrap(
    config_path: str,
    *,
    model: str = "",
    vector_backend: str = "",
    qdrant_url: str = "",
    embedding_model: str = "",
    chat_storage_class: str = "",
    chat_db_dsn: str = "",
) -> OrchidContext:
    """
    Load config, build reader, build graph — return a ready-to-use context.

    Chat storage is always initialized (defaults to SQLite at ~/.orchid/chats.db).
    """
    # Apply YAML config to environment — mirrors orchid-api/settings.py:_apply_yaml_config()
    if config_path:
        os.environ.setdefault("ORCHID_CONFIG", config_path)
        _apply_yaml_to_env(config_path)

    # Load YAML agent config
    agents_config_path = os.environ.get("AGENTS_CONFIG_PATH", "agents.yaml")
    agents_config = load_config(agents_config_path)

    # Resolve defaults from env
    resolved_model = model or os.environ.get("LITELLM_MODEL", "ollama/llama3.2")
    resolved_backend = vector_backend or os.environ.get("VECTOR_BACKEND", "qdrant")
    resolved_qdrant_url = qdrant_url or os.environ.get("QDRANT_URL", "http://qdrant:6333")
    resolved_embedding = embedding_model or os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

    # Build reader
    reader = build_reader(
        vector_backend=resolved_backend,
        qdrant_url=resolved_qdrant_url,
        embedding_model=resolved_embedding,
    )

    # Ensure collections
    if isinstance(reader, VectorStoreAdmin):
        namespaces = [a.rag.namespace for a in agents_config.agents.values() if a.rag.enabled and a.rag.namespace]
        if namespaces:
            await reader.ensure_collections([*namespaces, "uploads"])

    # Chat persistence — always initialized, defaults to SQLite
    resolved_storage_class = chat_storage_class or os.environ.get("CHAT_STORAGE_CLASS", "") or DEFAULT_STORAGE_CLASS
    resolved_dsn = chat_db_dsn or os.environ.get("CHAT_DB_DSN", "") or DEFAULT_STORAGE_DSN
    chat_repo = build_chat_storage(class_path=resolved_storage_class, dsn=resolved_dsn)
    await chat_repo.init_db()

    # MCP OAuth token storage — shares the same SQLite DB as chat persistence
    mcp_token_store = build_mcp_token_store(
        class_path=DEFAULT_TOKEN_STORE_CLASS,
        dsn=resolved_dsn,  # same DB file as chat storage
    )
    await mcp_token_store.init_db()

    # Build runtime
    runtime = OrchidRuntime(
        default_model=resolved_model,
        reader=reader,
        mcp_token_store=mcp_token_store,
    )

    # ── Checkpointer (optional — LangGraph state persistence) ──
    resolved_checkpointer_type = os.environ.get("CHECKPOINTER_TYPE", "")
    if resolved_checkpointer_type:
        from orchid_ai.checkpointing import build_checkpointer

        resolved_checkpointer_dsn = os.environ.get("CHECKPOINTER_DSN", "")
        checkpointer = await build_checkpointer(
            checkpointer_type=resolved_checkpointer_type,
            dsn=resolved_checkpointer_dsn,
        )
        runtime.checkpointer = checkpointer
        logger.info("[CLI] Checkpointer: %s", type(checkpointer).__name__)

    graph = build_graph(
        config=agents_config,
        runtime=runtime,
    )

    logger.info(
        "[CLI] Ready — model=%s, backend=%s, storage=%s, agents=%s",
        resolved_model,
        resolved_backend,
        resolved_storage_class.rsplit(".", 1)[-1],
        list(agents_config.agents.keys()),
    )

    return OrchidContext(
        graph=graph,
        reader=reader,
        chat_repo=chat_repo,
        config=agents_config,
        model=resolved_model,
        mcp_token_store=mcp_token_store,
        runtime=runtime,
    )


@asynccontextmanager
async def cli_context(config_path: str, *, model: str = ""):
    """Bootstrap and ensure clean shutdown (closes aiosqlite before event loop exits)."""
    ctx = await bootstrap(config_path, model=model)
    try:
        yield ctx
    finally:
        if ctx.runtime.checkpointer:
            from orchid_ai.checkpointing import shutdown_checkpointer

            await shutdown_checkpointer(ctx.runtime.checkpointer)
        if ctx.mcp_token_store:
            await ctx.mcp_token_store.close()
        await ctx.chat_repo.close()
