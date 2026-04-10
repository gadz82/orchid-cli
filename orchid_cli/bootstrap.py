"""
Shared bootstrapping — load config, build graph, initialize persistence.

Mirrors the lifespan logic from orchid-api but without FastAPI.
SQLite storage is always initialized by default (no external DB required).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from orchid.config.loader import load_config
from orchid.config.schema import AgentsConfig
from orchid.core.repository import VectorReader, VectorStoreAdmin
from orchid.graph.graph import build_graph
from orchid.persistence.base import ChatStorage
from orchid.persistence.factory import build_chat_storage
from orchid.rag.factory import build_reader

logger = logging.getLogger(__name__)

# ── YAML key → env var mapping (same as orchid-api/settings.py) ──────
_YAML_TO_ENV: dict[tuple[str, str], str] = {
    ("agents", "config_path"): "AGENTS_CONFIG_PATH",
    ("llm", "model"): "LITELLM_MODEL",
    ("llm", "ollama_api_base"): "OLLAMA_API_BASE",
    ("llm", "groq_api_key"): "GROQ_API_KEY",
    ("llm", "gemini_api_key"): "GEMINI_API_KEY",
    ("llm", "anthropic_api_key"): "ANTHROPIC_API_KEY",
    ("llm", "openai_api_key"): "OPENAI_API_KEY",
    ("auth", "dev_bypass"): "DEV_AUTH_BYPASS",
    ("auth", "identity_resolver_class"): "IDENTITY_RESOLVER_CLASS",
    ("auth", "domain"): "AUTH_DOMAIN",
    ("startup", "hook"): "STARTUP_HOOK",
    ("rag", "vector_backend"): "VECTOR_BACKEND",
    ("rag", "qdrant_url"): "QDRANT_URL",
    ("rag", "embedding_model"): "EMBEDDING_MODEL",
    ("rag", "openai_api_key"): "OPENAI_API_KEY",
    ("rag", "gemini_api_key"): "GEMINI_API_KEY",
    ("upload", "vision_model"): "VISION_MODEL",
    ("upload", "namespace"): "UPLOAD_NAMESPACE",
    ("upload", "max_size_mb"): "UPLOAD_MAX_SIZE_MB",
    ("upload", "chunk_size"): "CHUNK_SIZE",
    ("upload", "chunk_overlap"): "CHUNK_OVERLAP",
    ("storage", "class"): "CHAT_STORAGE_CLASS",
    ("storage", "dsn"): "CHAT_DB_DSN",
    ("mcp", "catalog_url"): "MCP_CATALOG_URL",
    ("mcp", "notifications_url"): "MCP_NOTIFICATIONS_URL",
    ("tracing", "langsmith_tracing"): "LANGSMITH_TRACING",
    ("tracing", "langsmith_api_key"): "LANGSMITH_API_KEY",
    ("tracing", "langsmith_project"): "LANGSMITH_PROJECT",
}


def _apply_yaml_to_env(config_path: str) -> None:
    """Parse orchid.yml and export values as env vars (if not already set).

    Storage settings (class, dsn) are skipped — the CLI has its own
    defaults (SQLite at ~/.orchid/chats.db) that are more appropriate
    than Docker-oriented paths often found in orchid.yml.
    """
    try:
        import yaml

        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("[CLI] Config file %s not found — ignoring", config_path)
        return

    # Storage config in orchid.yml is typically Docker-oriented (e.g. /data/chats.db).
    # The CLI defaults to ~/.orchid/chats.db which is always writable.
    _SKIP_SECTIONS = {"storage"}

    for section, body in data.items():
        if not isinstance(body, dict) or section in _SKIP_SECTIONS:
            continue
        for key, value in body.items():
            env_var = _YAML_TO_ENV.get((section, key))
            if env_var and env_var not in os.environ:
                os.environ[env_var] = str(value)

    logger.debug("[CLI] Applied YAML config from %s", config_path)


# Defaults — SQLite storage ships with orchid, no external DB needed
DEFAULT_STORAGE_CLASS = "orchid.persistence.sqlite.SQLiteChatStorage"
DEFAULT_STORAGE_DSN = "~/.orchid/chats.db"


@dataclass
class OrchidContext:
    """Runtime context for CLI operations."""

    graph: Any
    reader: VectorReader
    chat_repo: ChatStorage
    config: AgentsConfig
    model: str


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

    # Build graph
    graph = build_graph(
        config=agents_config,
        default_model=resolved_model,
        reader=reader,
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
    )


@asynccontextmanager
async def cli_context(config_path: str, *, model: str = ""):
    """Bootstrap and ensure clean shutdown (closes aiosqlite before event loop exits)."""
    ctx = await bootstrap(config_path, model=model)
    try:
        yield ctx
    finally:
        await ctx.chat_repo.close()
