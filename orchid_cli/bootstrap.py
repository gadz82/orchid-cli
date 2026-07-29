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
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from orchid_ai import Orchid
from orchid_ai.content.local import LocalFileContentSource

logger = logging.getLogger(__name__)


# Public defaults — referenced by command modules (e.g. mcp, auth) that
# want to honour the CLI's SQLite-first convention.
DEFAULT_STORAGE_CLASS = "orchid_ai.persistence.sqlite.OrchidSQLiteChatStorage"
DEFAULT_STORAGE_DSN = "~/.orchid/chats.db"
DEFAULT_TOKEN_STORE_CLASS = "orchid_ai.persistence.mcp_token_sqlite.OrchidSQLiteMCPTokenStore"

# ChromaDB defaults — zero-infrastructure RAG for the CLI via
# orchid-rag-chroma plugin.  The plugin auto-registers ``"chroma"``
# in VECTOR_BACKEND_REGISTRY via entry points.
DEFAULT_VECTOR_BACKEND = "chroma"
DEFAULT_CHROMA_PATH = "~/.orchid/chroma"


def _has_cli_rag_section(config_path: str) -> bool:
    """Return True if the YAML config has a ``cli_rag:`` section.

    When ``cli_rag:`` is present, the CLI uses it instead of ``rag:``
    for vector backend and embedding configuration.  This allows
    Docker-based examples (with ``rag.vector_backend: qdrant``) to
    run locally via the CLI without requiring Qdrant infrastructure.
    """
    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return "cli_rag" in data and isinstance(data["cli_rag"], dict)
    except (FileNotFoundError, yaml.YAMLError):
        return False


def apply_cli_config(config_path: str) -> None:
    """Apply ``orchid.yml`` values to env vars, honouring the CLI's
    ``skip_sections={"storage"}`` convention.

    When a ``cli_rag:`` section is present in the YAML, the ``rag:``
    section is skipped so that CLI-specific RAG settings (typically
    ChromaDB + local embeddings) win over the API's RAG settings
    (typically Qdrant + cloud embeddings).

    Silently skips ``.md`` files — Markdown config applies its own
    env-var mapping through :class:`orchid_ai.Orchid`.

    Call this explicitly at command entry points (before :func:`bootstrap`)
    to make env-var mutation an obvious, visible step.  :func:`bootstrap`
    still calls it internally — a second call is idempotent because
    :func:`apply_yaml_to_env` only sets vars that are not already present.
    """
    from pathlib import Path

    if Path(config_path).suffix.lower() == ".md":
        return

    from orchid_ai.config.yaml_env import apply_yaml_to_env

    skip = {"storage"}
    if _has_cli_rag_section(config_path):
        skip.add("rag")
        logger.info("[CLI] cli_rag: section detected — using CLI-specific RAG config")

    apply_yaml_to_env(config_path, skip_sections=skip)


async def bootstrap(
    config_path: str,
    *,
    model: str = "",
    vector_backend: str = "",
    qdrant_url: str = "",
    embedding_model: str = "",
    chroma_path: str = "",
    chat_storage_class: str = "",
    chat_db_dsn: str = "",
    chat_extra_migrations_package: str | None = None,
    content_paths: list[str] | None = None,
) -> Orchid:
    """Build an :class:`Orchid` instance with CLI-friendly defaults.

    The CLI's SQLite-first defaults (``~/.orchid/chats.db``) win over
    any ``storage:`` block in ``orchid.yml``; the CLI is typically run
    outside Docker where the YAML's container paths would be wrong.

    ``chat_extra_migrations_package`` forwards an integrator-supplied
    migrations package to :class:`Orchid`.  When left ``None`` the
    value is picked up from the ``CHAT_EXTRA_MIGRATIONS_PACKAGE`` env
    var.

    After the framework is built, ``auth.mode: none`` MCP servers are
    warmed proactively so the per-request hot path stops paying the
    capability discovery cost.  Per-user warming (passthrough / oauth)
    happens in the :func:`commands._session.resolve_session` helper.

    Returns the fully-started :class:`Orchid` facade.  Pair with
    :meth:`Orchid.close` (or use :func:`cli_context`) to ensure
    aiosqlite / checkpointer / token-store connections are released
    before the event loop exits.
    """
    # Ensure CWD is importable — console-script invocations may run
    # without the working directory on sys.path, breaking startup-hook
    # import paths like ``examples.recipes.hooks.startup.seed_recipes``.
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    # Resolve CLI-specific defaults (Chroma first) and seed env vars so
    # downstream code (including ``build_reader``) sees them.
    resolved_backend = vector_backend or os.environ.get("VECTOR_BACKEND", DEFAULT_VECTOR_BACKEND)
    resolved_chroma = chroma_path or os.environ.get("CHROMA_PATH", DEFAULT_CHROMA_PATH)
    os.environ.setdefault("VECTOR_BACKEND", resolved_backend)
    os.environ.setdefault("CHROMA_PATH", resolved_chroma)

    # CLI convention: storage block in YAML does NOT override our SQLite
    # default.  Everything else in YAML → env propagates as usual.
    # When cli_rag: is present, rag: is also skipped so CLI-specific
    # RAG settings (chroma + local embeddings) win over API settings.

    # Build content sources from --content-path CLI args
    content_sources = None
    if content_paths:
        content_sources = [LocalFileContentSource(path=str(Path(p).resolve())) for p in content_paths]

    skip_sections = {"storage"}
    if _has_cli_rag_section(config_path):
        skip_sections.add("rag")

    orchid = await Orchid.from_config_path(
        config_path=config_path,
        apply_yaml=bool(config_path),
        skip_yaml_sections=skip_sections,
        model=model,
        vector_backend=resolved_backend,
        qdrant_url=qdrant_url,
        embedding_model=embedding_model,
        chat_storage_class=chat_storage_class,
        chat_db_dsn=chat_db_dsn,
        chat_extra_migrations_package=chat_extra_migrations_package,
        content_sources=content_sources,
    )

    # Warm ``auth.mode: none`` MCP capabilities up front so the user
    # never sees the discovery latency on the first chat.  Failures
    # are advisory — the CLI keeps going regardless.
    try:
        report = await orchid.warm_unauthenticated_capabilities()
        logger.info(
            "[CLI] MCP warm-up: warmed=%s, skipped=%s, failed=%s",
            report.warmed,
            report.skipped,
            report.failed,
        )
    except Exception as exc:
        logger.warning("[CLI] MCP warm-up raised: %s", exc)

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
