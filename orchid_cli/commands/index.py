"""
Index commands — seed the vector store with data (at any time).

Subcommands::

    orchid index file <path> -n <namespace> -c orchid.yml
        Index a single document file (PDF, DOCX, XLSX, CSV, TXT, MD, PNG, JPG).
        Uses the same ingestion pipeline as the /upload endpoint.

    orchid index dir <path> -n <namespace> -c orchid.yml
        Recursively index all supported files in a directory.

    orchid index text -n <namespace> -c orchid.yml "inline content to index"
        Index a single block of inline text.

    orchid index json-file <path> -n <namespace> -c orchid.yml
        Bulk-index entries from a JSON array of {content, metadata?, id?}.

Scope options shared by all commands:
    --tenant / -t    Tenant ID (default: "default").  Use "__shared__" for
                     cross-tenant seed data.
    --scope / -s     Scope level: tenant | shared | user (default: "tenant").
    --user           User ID for user-scoped docs (requires --scope user).

Markdown / front-matter options (``file`` and ``dir``):
    --front-matter         Parse YAML front-matter from Markdown files.
    --id-field <name>      Front-matter field to use as a stable source id.

Idempotency options (``file`` and ``dir``):
    --manifest/--no-manifest     Enable the ingestion manifest (default: on for
                                 ``dir``, off for ``file``).
    --manifest-dsn <dsn>         SQLite path or ``postgresql://...`` DSN.
    --manifest-path <path>       Alias for a SQLite manifest file path.
    --prune                      Delete vectors for removed source files
                                 (``dir`` only).
    --force                      Re-index even if the manifest says unchanged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import typer
from orchid_ai.core.ingestion_manifest import OrchidIngestionManifest
from orchid_ai.core.repository import Document, OrchidDocument, OrchidVectorWriter
from orchid_ai.documents.chunker import ChunkConfig
from orchid_ai.documents.pipeline import ingest_document
from orchid_ai.documents.strategies import FrontMatterIngestion, RecursiveIngestion
from orchid_ai.rag.scopes import SHARED_TENANT, OrchidRAGScope
from rich.console import Console

from .._typer_async import async_command

logger = logging.getLogger(__name__)

app = typer.Typer(help="Vector store indexing (on-demand RAG seeding)", no_args_is_help=True)
console = Console()


# ── Defaults ───────────────────────────────────────────────────

_SUPPORTED_EXTS = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md", ".png", ".jpg", ".jpeg"}
DEFAULT_MANIFEST_DSN = os.path.expanduser("~/.orchid/index_manifest.db")


# ── Manifest factory ───────────────────────────────────────────


def _build_manifest(*, manifest_dsn: str, manifest_path: str) -> OrchidIngestionManifest:
    """Create a manifest store from CLI flags.

    ``--manifest-dsn`` takes precedence.  If it starts with ``postgresql://``,
    the PostgreSQL backend is used; otherwise SQLite.  ``--manifest-path`` is
    a convenience alias for a SQLite file path.
    """
    dsn = manifest_dsn or manifest_path or DEFAULT_MANIFEST_DSN
    if dsn.startswith("postgresql://"):
        from orchid_storage_postgres.ingestion_manifest import OrchidPostgresIngestionManifest

        return OrchidPostgresIngestionManifest(dsn=dsn)

    from orchid_ai.persistence.sqlite_ingestion_manifest import OrchidSQLiteIngestionManifest

    return OrchidSQLiteIngestionManifest(dsn=dsn)


async def _manifest_context(
    *,
    enabled: bool,
    manifest_dsn: str,
    manifest_path: str,
) -> OrchidIngestionManifest | None:
    """Initialise and return a manifest store, or ``None`` if disabled."""
    if not enabled:
        return None
    manifest = _build_manifest(manifest_dsn=manifest_dsn, manifest_path=manifest_path)
    await manifest.init_db()
    return manifest


def _build_ingestion(
    *,
    file_path: Path,
    front_matter: bool,
    id_field: str,
    chunk_size: int,
    chunk_overlap: int,
) -> Any:
    """Choose the ingestion strategy based on CLI flags and file type."""
    chunk_config = ChunkConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if front_matter and file_path.suffix.lower() == ".md":
        return FrontMatterIngestion(inner=RecursiveIngestion(chunk_config), id_field=id_field)
    return RecursiveIngestion(chunk_config)


def _compute_hash(content: bytes) -> str:
    """SHA-256 hex digest of file contents."""
    return hashlib.sha256(content).hexdigest()


# ── Shared helpers ──────────────────────────────────────────────


def _resolve_scope(tenant: str, scope: str, user: str) -> tuple[str, str]:
    """Resolve tenant_id and scope label from CLI flags.

    Returns (tenant_id, scope_label) for metadata.
    """
    scope_lower = scope.strip().lower()

    if scope_lower == "shared":
        return SHARED_TENANT, "tenant"
    if scope_lower == "user":
        if not user:
            console.print("[red]Error:[/red] --scope user requires --user <user_id>")
            raise typer.Exit(code=1)
        return tenant, "user"
    if scope_lower == "tenant":
        return tenant, "tenant"

    console.print(f"[red]Error:[/red] Unknown scope '{scope}'. Use: tenant | shared | user")
    raise typer.Exit(code=1)


def _build_metadata(
    tenant_id: str,
    scope_label: str,
    user_id: str,
    source: str,
) -> dict:
    meta: dict = {"tenant_id": tenant_id, "scope": scope_label, "source": source}
    if user_id and scope_label == "user":
        meta["user_id"] = user_id
    return meta


async def _require_writer(ctx) -> OrchidVectorWriter:
    reader = ctx.runtime.get_reader()
    if not isinstance(reader, OrchidVectorWriter):
        console.print("[red]Error:[/red] Vector store does not support writing (backend may be 'null')")
        raise typer.Exit(code=1)
    return reader


# ── Command: file ──────────────────────────────────────────────


@app.command()
@async_command
async def file(
    path: str = typer.Argument(..., help="Path to file to index"),
    namespace: str = typer.Option(..., "--namespace", "-n", help="Target collection name"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    tenant: str = typer.Option("default", "--tenant", "-t", help="Tenant ID ('__shared__' for cross-tenant)"),
    scope: str = typer.Option("tenant", "--scope", "-s", help="Scope: tenant | shared | user"),
    user: str = typer.Option("", "--user", help="User ID (required when --scope user)"),
    vision_model: str = typer.Option("", "--vision-model", help="Vision LLM for image parsing"),
    chunk_size: int = typer.Option(1000, "--chunk-size", help="Characters per chunk"),
    chunk_overlap: int = typer.Option(200, "--chunk-overlap", help="Overlap between chunks"),
    front_matter: bool = typer.Option(False, "--front-matter", help="Parse YAML front-matter from Markdown files"),
    id_field: str = typer.Option("", "--id-field", help="Front-matter field to use as stable source id"),
    manifest: bool = typer.Option(False, "--manifest/--no-manifest", help="Enable idempotency manifest"),
    manifest_dsn: str = typer.Option("", "--manifest-dsn", help="Manifest DB DSN (SQLite path or postgresql://...)"),
    manifest_path: str = typer.Option("", "--manifest-path", help="Alias for SQLite manifest file path"),
    force: bool = typer.Option(False, "--force", help="Re-index even if the manifest says unchanged"),
) -> None:
    """Index a single document file into a namespace.

    Supported: PDF, DOCX, XLSX, CSV, TXT, MD, PNG, JPG.
    Uses the same ingestion pipeline as the ``/upload`` endpoint
    (parse → chunk → embed → store).
    """
    await _index_file(
        path,
        namespace,
        config,
        tenant,
        scope,
        user,
        vision_model,
        chunk_size,
        chunk_overlap,
        front_matter=front_matter,
        id_field=id_field,
        manifest=manifest,
        manifest_dsn=manifest_dsn,
        manifest_path=manifest_path,
        force=force,
    )


async def _index_file(
    path: str,
    namespace: str,
    config_path: str,
    tenant: str,
    scope: str,
    user: str,
    vision_model: str,
    chunk_size: int,
    chunk_overlap: int,
    *,
    front_matter: bool,
    id_field: str,
    manifest: bool,
    manifest_dsn: str,
    manifest_path: str,
    force: bool,
) -> None:
    from ..bootstrap import cli_context

    file_path = Path(path).expanduser()
    if not file_path.exists() or not file_path.is_file():
        console.print(f"[red]Error:[/red] Not a file: {file_path}")
        raise typer.Exit(code=1)

    tenant_id, scope_label = _resolve_scope(tenant, scope, user)

    manifest_store: OrchidIngestionManifest | None = None
    try:
        manifest_store = await _manifest_context(
            enabled=manifest,
            manifest_dsn=manifest_dsn,
            manifest_path=manifest_path,
        )

        async with cli_context(config_path) as ctx:
            writer = await _require_writer(ctx)
            scope_obj = OrchidRAGScope(tenant_id=tenant_id, user_id=user, chat_id="", agent_id="")
            ingestion = _build_ingestion(
                file_path=file_path,
                front_matter=front_matter,
                id_field=id_field,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )

            source_id = file_path.name
            file_bytes = file_path.read_bytes()
            content_hash = _compute_hash(file_bytes)

            if manifest_store and await manifest_store.should_skip(source_id, content_hash, namespace) and not force:
                console.print(f"[dim]Skipping unchanged file:[/dim] {file_path.name}")
                return

            console.print(f"[dim]Reading {file_path}...[/dim]")
            documents_out: list[OrchidDocument] = []
            count = await ingest_document(
                file_bytes=file_bytes,
                filename=file_path.name,
                scope=scope_obj,
                namespace=namespace,
                writer=writer,
                ingestion=ingestion,
                vision_model=vision_model,
                documents_out=documents_out,
            )

            if count == 0:
                console.print(f"[yellow]Indexed 0 chunks[/yellow] from {file_path.name} (empty or parse failed)")
            else:
                console.print(
                    f"[green]Indexed[/green] {count} chunk(s) from [bold]{file_path.name}[/bold] "
                    f"into namespace '{namespace}' (tenant={tenant_id}, scope={scope_label})"
                )

            if manifest_store:
                document_ids = [doc.id for doc in documents_out]
                await manifest_store.record(source_id, content_hash, namespace, document_ids)
    finally:
        if manifest_store:
            await manifest_store.close()


# ── Command: dir ────────────────────────────────────────────────


@app.command()
@async_command
async def dir(
    path: str = typer.Argument(..., help="Directory to index (recursively)"),
    namespace: str = typer.Option(..., "--namespace", "-n", help="Target collection name"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    tenant: str = typer.Option("default", "--tenant", "-t", help="Tenant ID"),
    scope: str = typer.Option("tenant", "--scope", "-s", help="Scope: tenant | shared | user"),
    user: str = typer.Option("", "--user", help="User ID (required when --scope user)"),
    vision_model: str = typer.Option("", "--vision-model", help="Vision LLM for image parsing"),
    chunk_size: int = typer.Option(1000, "--chunk-size", help="Characters per chunk"),
    chunk_overlap: int = typer.Option(200, "--chunk-overlap", help="Overlap between chunks"),
    pattern: str = typer.Option("", "--pattern", help="Glob pattern (e.g. '*.md'). Default: all supported extensions."),
    front_matter: bool = typer.Option(False, "--front-matter", help="Parse YAML front-matter from Markdown files"),
    id_field: str = typer.Option("", "--id-field", help="Front-matter field to use as stable source id"),
    manifest: bool = typer.Option(True, "--manifest/--no-manifest", help="Enable idempotency manifest"),
    manifest_dsn: str = typer.Option("", "--manifest-dsn", help="Manifest DB DSN (SQLite path or postgresql://...)"),
    manifest_path: str = typer.Option("", "--manifest-path", help="Alias for SQLite manifest file path"),
    prune: bool = typer.Option(False, "--prune", help="Delete vectors for source files no longer present"),
    force: bool = typer.Option(False, "--force", help="Re-index even if the manifest says unchanged"),
) -> None:
    """Recursively index all supported files in a directory."""
    await _index_dir(
        path,
        namespace,
        config,
        tenant,
        scope,
        user,
        vision_model,
        chunk_size,
        chunk_overlap,
        pattern,
        front_matter=front_matter,
        id_field=id_field,
        manifest=manifest,
        manifest_dsn=manifest_dsn,
        manifest_path=manifest_path,
        prune=prune,
        force=force,
    )


async def _index_dir(
    path: str,
    namespace: str,
    config_path: str,
    tenant: str,
    scope: str,
    user: str,
    vision_model: str,
    chunk_size: int,
    chunk_overlap: int,
    pattern: str,
    *,
    front_matter: bool,
    id_field: str,
    manifest: bool,
    manifest_dsn: str,
    manifest_path: str,
    prune: bool,
    force: bool,
) -> None:
    from ..bootstrap import cli_context

    dir_path = Path(path).expanduser()
    if not dir_path.exists() or not dir_path.is_dir():
        console.print(f"[red]Error:[/red] Not a directory: {dir_path}")
        raise typer.Exit(code=1)

    if pattern:
        files = sorted(dir_path.rglob(pattern))
    else:
        files = sorted(p for p in dir_path.rglob("*") if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS)

    if not files:
        console.print(f"[yellow]No matching files found in {dir_path}[/yellow]")
        return

    console.print(f"[dim]Found {len(files)} file(s) to index.[/dim]")
    tenant_id, scope_label = _resolve_scope(tenant, scope, user)

    manifest_store: OrchidIngestionManifest | None = None
    try:
        manifest_store = await _manifest_context(
            enabled=manifest,
            manifest_dsn=manifest_dsn,
            manifest_path=manifest_path,
        )

        async with cli_context(config_path) as ctx:
            writer = await _require_writer(ctx)
            scope_obj = OrchidRAGScope(tenant_id=tenant_id, user_id=user, chat_id="", agent_id="")

            total_chunks = 0
            successes = 0
            skipped = 0
            failures = 0
            present_sources: set[str] = set()

            for f in files:
                source_id = str(f.relative_to(dir_path))
                present_sources.add(source_id)
                try:
                    file_bytes = f.read_bytes()
                    content_hash = _compute_hash(file_bytes)

                    if (
                        manifest_store
                        and await manifest_store.should_skip(source_id, content_hash, namespace)
                        and not force
                    ):
                        skipped += 1
                        console.print(f"  [dim]unchanged[/dim]  {f.relative_to(dir_path)}")
                        continue

                    ingestion = _build_ingestion(
                        file_path=f,
                        front_matter=front_matter,
                        id_field=id_field,
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                    )
                    documents_out: list[OrchidDocument] = []
                    count = await ingest_document(
                        file_bytes=file_bytes,
                        filename=f.name,
                        scope=scope_obj,
                        namespace=namespace,
                        writer=writer,
                        ingestion=ingestion,
                        vision_model=vision_model,
                        documents_out=documents_out,
                    )

                    if count > 0:
                        successes += 1
                        total_chunks += count
                        console.print(f"  [green]{count} chunks[/green]  {f.relative_to(dir_path)}")
                    else:
                        console.print(f"  [yellow]0 chunks[/yellow]  {f.relative_to(dir_path)} (empty/unparseable)")

                    if manifest_store:
                        document_ids = [doc.id for doc in documents_out]
                        await manifest_store.record(source_id, content_hash, namespace, document_ids)
                except Exception as exc:
                    failures += 1
                    console.print(f"  [red]failed[/red]  {f.relative_to(dir_path)}: {exc}")

            if manifest_store and prune:
                pruned = await _prune_missing_sources(
                    manifest=manifest_store,
                    writer=writer,
                    namespace=namespace,
                    present_sources=present_sources,
                )
                if pruned:
                    console.print(f"\n[yellow]Pruned[/yellow] {pruned} removed source(s) from '{namespace}'")

            console.print(
                f"\n[green]Done.[/green] {successes} file(s) indexed, {skipped} skipped, "
                f"{total_chunks} total chunk(s), {failures} failure(s). "
                f"Namespace '{namespace}' (tenant={tenant_id}, scope={scope_label})"
            )
    finally:
        if manifest_store:
            await manifest_store.close()


async def _prune_missing_sources(
    manifest: OrchidIngestionManifest,
    writer: OrchidVectorWriter,
    namespace: str,
    present_sources: set[str],
) -> int:
    """Delete vectors and manifest rows for sources no longer present.

    Returns the number of sources pruned.
    """
    known = await manifest.list_known(namespace)
    missing = known - present_sources
    for source_id in missing:
        document_ids = await manifest.get_document_ids(source_id, namespace)
        if document_ids:
            await writer.delete(document_ids, namespace)
        await manifest.remove(source_id, namespace)
    return len(missing)


# ── Command: text ───────────────────────────────────────────────


@app.command()
@async_command
async def text(
    content: str = typer.Argument(..., help="Inline text to index as a single document"),
    namespace: str = typer.Option(..., "--namespace", "-n", help="Target collection name"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    tenant: str = typer.Option("default", "--tenant", "-t", help="Tenant ID"),
    scope: str = typer.Option("tenant", "--scope", "-s", help="Scope: tenant | shared | user"),
    user: str = typer.Option("", "--user", help="User ID (required when --scope user)"),
    title: str = typer.Option("", "--title", help="Optional title stored in metadata"),
    doc_id: str = typer.Option("", "--id", help="Optional document ID (auto-generated if empty)"),
) -> None:
    """Index a single block of inline text as a document.

    The text is stored as one document (no chunking).  Useful for seeding
    FAQ snippets, summaries, or short guides.
    """
    await _index_text(content, namespace, config, tenant, scope, user, title, doc_id)


async def _index_text(
    content: str,
    namespace: str,
    config_path: str,
    tenant: str,
    scope: str,
    user: str,
    title: str,
    doc_id: str,
) -> None:
    from ..bootstrap import cli_context

    content = (content or "").strip()
    if not content:
        console.print("[red]Error:[/red] Empty content")
        raise typer.Exit(code=1)

    tenant_id, scope_label = _resolve_scope(tenant, scope, user)

    async with cli_context(config_path) as ctx:
        writer = await _require_writer(ctx)

        if not doc_id:
            doc_id = f"inline-{hashlib.sha256(content.encode()).hexdigest()[:12]}"

        metadata = _build_metadata(tenant_id, scope_label, user, source="inline")
        if title:
            metadata["title"] = title

        doc = Document(id=doc_id, page_content=content, metadata=metadata)
        await writer.upsert([doc], namespace)

        console.print(
            f"[green]Indexed[/green] 1 document (id={doc_id}) into namespace '{namespace}' "
            f"(tenant={tenant_id}, scope={scope_label})"
        )


# ── Command: json-file ─────────────────────────────────────────


@app.command("json-file")
@async_command
async def json_file(
    path: str = typer.Argument(..., help="Path to JSON file with array of {content, metadata?, id?}"),
    namespace: str = typer.Option(..., "--namespace", "-n", help="Target collection name"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    tenant: str = typer.Option("default", "--tenant", "-t", help="Tenant ID"),
    scope: str = typer.Option("tenant", "--scope", "-s", help="Scope: tenant | shared | user"),
    user: str = typer.Option("", "--user", help="User ID (required when --scope user)"),
) -> None:
    """Bulk-index documents from a JSON file.

    The JSON must be an array of objects with at least ``content`` (string).
    Optional per-entry fields: ``id`` (string), ``metadata`` (dict).
    Scope fields (tenant_id, scope) are auto-filled from CLI flags.

    Example::

        [
          {"id": "faq-1", "content": "Our refund policy is 30 days...",
           "metadata": {"category": "policy"}},
          {"content": "Business hours are 9-5 EST..."}
        ]
    """
    await _index_json(path, namespace, config, tenant, scope, user)


async def _index_json(
    path: str,
    namespace: str,
    config_path: str,
    tenant: str,
    scope: str,
    user: str,
) -> None:
    from ..bootstrap import cli_context

    file_path = Path(path).expanduser()
    if not file_path.exists():
        console.print(f"[red]Error:[/red] File not found: {file_path}")
        raise typer.Exit(code=1)

    try:
        entries = json.loads(file_path.read_text())
    except json.JSONDecodeError as exc:
        console.print(f"[red]Error:[/red] Invalid JSON: {exc}")
        raise typer.Exit(code=1) from exc

    if not isinstance(entries, list):
        console.print("[red]Error:[/red] JSON must be an array of objects")
        raise typer.Exit(code=1)

    tenant_id, scope_label = _resolve_scope(tenant, scope, user)

    async with cli_context(config_path) as ctx:
        writer = await _require_writer(ctx)

        docs = []
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict) or "content" not in entry:
                console.print(f"[yellow]Skipping entry #{i}:[/yellow] missing 'content' field")
                continue

            content = str(entry["content"]).strip()
            if not content:
                continue

            entry_id = entry.get("id") or f"json-{hashlib.sha256(content.encode()).hexdigest()[:12]}"
            metadata = _build_metadata(tenant_id, scope_label, user, source=f"json:{file_path.name}")
            user_meta = entry.get("metadata") or {}
            if isinstance(user_meta, dict):
                for k, v in user_meta.items():
                    if k not in ("tenant_id", "scope", "user_id"):
                        metadata[k] = v

            docs.append(Document(id=entry_id, page_content=content, metadata=metadata))

        if not docs:
            console.print("[yellow]No valid entries to index.[/yellow]")
            return

        await writer.upsert(docs, namespace)
        console.print(
            f"[green]Indexed[/green] {len(docs)} document(s) from {file_path.name} into "
            f"namespace '{namespace}' (tenant={tenant_id}, scope={scope_label})"
        )
