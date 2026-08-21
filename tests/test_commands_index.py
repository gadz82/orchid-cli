"""Tests for orchid_cli.commands.index — RAG indexing with idempotency."""

from __future__ import annotations

import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from orchid_ai.core.repository import OrchidDocument, OrchidVectorWriter
from orchid_ai.documents.strategies import FrontMatterIngestion, RecursiveIngestion
from orchid_ai.persistence.sqlite_ingestion_manifest import OrchidSQLiteIngestionManifest
from orchid_ai.rag.scopes import OrchidRAGScope, scope_key

_SCOPE_KEY = scope_key(OrchidRAGScope(tenant_id="default"))


class MockWriter(OrchidVectorWriter):
    """In-memory vector writer stub that satisfies the OrchidVectorWriter ABC."""

    def __init__(self) -> None:
        self.upserted: list[tuple[list[OrchidDocument], str]] = []
        self.deleted: list[tuple[list[str], str]] = []

    async def index(self, documents: list[OrchidDocument], namespace: str) -> None:
        pass

    async def upsert(self, documents: list[OrchidDocument], namespace: str) -> None:
        self.upserted.append((documents, namespace))

    async def delete(self, document_ids: list[str], namespace: str) -> None:
        self.deleted.append((document_ids, namespace))


@pytest.fixture
def mock_context_with_writer(mock_context):
    writer = MockWriter()
    mock_context.runtime.get_reader.return_value = writer
    return mock_context, writer


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def manifest_path(tmp_path):
    return str(tmp_path / "manifest.db")


def _patch_cli_context(mock_context):
    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        yield mock_context

    return patch("orchid_cli.bootstrap.cli_context", _ctx)


class TestBuildIngestion:
    def test_front_matter_for_markdown(self):
        from orchid_cli.commands.index import _build_ingestion

        ingestion = _build_ingestion(
            file_path=Path("page.md"),
            front_matter=True,
            id_field="page_id",
            chunk_size=500,
            chunk_overlap=50,
        )
        assert isinstance(ingestion, FrontMatterIngestion)

    def test_recursive_for_non_markdown(self):
        from orchid_cli.commands.index import _build_ingestion

        ingestion = _build_ingestion(
            file_path=Path("doc.pdf"),
            front_matter=True,
            id_field="page_id",
            chunk_size=500,
            chunk_overlap=50,
        )
        assert isinstance(ingestion, RecursiveIngestion)

    def test_recursive_when_front_matter_disabled(self):
        from orchid_cli.commands.index import _build_ingestion

        ingestion = _build_ingestion(
            file_path=Path("page.md"),
            front_matter=False,
            id_field="page_id",
            chunk_size=500,
            chunk_overlap=50,
        )
        assert isinstance(ingestion, RecursiveIngestion)


class TestBuildManifest:
    def test_sqlite_default(self):
        from orchid_cli.commands.index import _build_manifest

        manifest = _build_manifest(manifest_dsn="", manifest_path="/tmp/test.db")
        assert isinstance(manifest, OrchidSQLiteIngestionManifest)

    def test_sqlite_by_dsn(self):
        from orchid_cli.commands.index import _build_manifest

        manifest = _build_manifest(manifest_dsn="/tmp/test.db", manifest_path="")
        assert isinstance(manifest, OrchidSQLiteIngestionManifest)

    def test_postgres_by_dsn(self):
        from orchid_cli.commands.index import _build_manifest

        mock_cls = MagicMock()
        fake_module = MagicMock()
        fake_module.OrchidPostgresIngestionManifest = mock_cls
        with patch.dict("sys.modules", {"orchid_storage_postgres.ingestion_manifest": fake_module}):
            manifest = _build_manifest(
                manifest_dsn="postgresql://localhost/db",
                manifest_path="",
            )
            mock_cls.assert_called_once_with(dsn="postgresql://localhost/db")
            assert manifest is mock_cls.return_value


class TestIndexDir:
    @pytest.mark.asyncio
    async def test_indexes_new_files(self, mock_context_with_writer, temp_dir, manifest_path):
        from orchid_cli.commands.index import _index_dir

        mock_context, _writer = mock_context_with_writer
        (temp_dir / "a.md").write_text("# A\n\ncontent a")

        with (
            _patch_cli_context(mock_context),
            patch("orchid_cli.commands.index.ingest_document", AsyncMock(return_value=2)) as mock_ingest,
        ):
            await _index_dir(
                path=str(temp_dir),
                namespace="ns-1",
                config_path="",
                tenant="default",
                scope="tenant",
                user="",
                vision_model="",
                chunk_size=1000,
                chunk_overlap=200,
                pattern="*.md",
                front_matter=False,
                id_field="",
                manifest=True,
                manifest_dsn="",
                manifest_path=manifest_path,
                prune=False,
                force=False,
            )

        mock_ingest.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_unchanged_files(self, mock_context_with_writer, temp_dir, manifest_path):
        from orchid_cli.commands.index import _index_dir

        mock_context, _writer = mock_context_with_writer
        (temp_dir / "a.md").write_text("# A\n\ncontent a")

        manifest = OrchidSQLiteIngestionManifest(dsn=manifest_path)
        await manifest.init_db()
        await manifest.record("a.md", "hash", "ns-1", ["doc-1"], scope=_SCOPE_KEY)
        await manifest.close()

        with (
            _patch_cli_context(mock_context),
            patch("orchid_cli.commands.index.ingest_document", AsyncMock(return_value=2)) as mock_ingest,
            patch("orchid_cli.commands.index._compute_hash", return_value="hash"),
        ):
            await _index_dir(
                path=str(temp_dir),
                namespace="ns-1",
                config_path="",
                tenant="default",
                scope="tenant",
                user="",
                vision_model="",
                chunk_size=1000,
                chunk_overlap=200,
                pattern="*.md",
                front_matter=False,
                id_field="",
                manifest=True,
                manifest_dsn="",
                manifest_path=manifest_path,
                prune=False,
                force=False,
            )

        mock_ingest.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_force_reindexes_unchanged(self, mock_context_with_writer, temp_dir, manifest_path):
        from orchid_cli.commands.index import _index_dir

        mock_context, _writer = mock_context_with_writer
        (temp_dir / "a.md").write_text("# A\n\ncontent a")

        manifest = OrchidSQLiteIngestionManifest(dsn=manifest_path)
        await manifest.init_db()
        await manifest.record("a.md", "hash", "ns-1", ["doc-1"], scope=_SCOPE_KEY)
        await manifest.close()

        with (
            _patch_cli_context(mock_context),
            patch("orchid_cli.commands.index.ingest_document", AsyncMock(return_value=2)) as mock_ingest,
            patch("orchid_cli.commands.index._compute_hash", return_value="hash"),
        ):
            await _index_dir(
                path=str(temp_dir),
                namespace="ns-1",
                config_path="",
                tenant="default",
                scope="tenant",
                user="",
                vision_model="",
                chunk_size=1000,
                chunk_overlap=200,
                pattern="*.md",
                front_matter=False,
                id_field="",
                manifest=True,
                manifest_dsn="",
                manifest_path=manifest_path,
                prune=False,
                force=True,
            )

        mock_ingest.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_prune_removes_missing_sources(self, mock_context_with_writer, temp_dir, manifest_path):
        from orchid_cli.commands.index import _index_dir

        mock_context, writer = mock_context_with_writer
        (temp_dir / "a.md").write_text("# A\n\ncontent a")

        manifest = OrchidSQLiteIngestionManifest(dsn=manifest_path)
        await manifest.init_db()
        await manifest.record("old.md", "hash", "ns-1", ["doc-old-0"], scope=_SCOPE_KEY)
        await manifest.close()

        def fake_ingest(*args, documents_out=None, **kwargs):
            if documents_out is not None:
                documents_out.append(OrchidDocument(id="doc-a-0", page_content="x", metadata={}))
            return 1

        with (
            _patch_cli_context(mock_context),
            patch("orchid_cli.commands.index.ingest_document", AsyncMock(side_effect=fake_ingest)),
        ):
            await _index_dir(
                path=str(temp_dir),
                namespace="ns-1",
                config_path="",
                tenant="default",
                scope="tenant",
                user="",
                vision_model="",
                chunk_size=1000,
                chunk_overlap=200,
                pattern="*.md",
                front_matter=False,
                id_field="",
                manifest=True,
                manifest_dsn="",
                manifest_path=manifest_path,
                prune=True,
                force=False,
            )

        assert any(document_ids == ["doc-old-0"] and namespace == "ns-1" for document_ids, namespace in writer.deleted)


class TestPruneMissingSources:
    @pytest.mark.asyncio
    async def test_prune_deletes_missing(self):
        from orchid_cli.commands.index import _prune_missing_sources

        manifest = AsyncMock()
        manifest.list_known = AsyncMock(return_value={"a.md", "b.md"})
        manifest.get_document_ids = AsyncMock(side_effect=lambda s, n, sc: [f"{s}-0"])
        manifest.remove = AsyncMock()

        writer = MockWriter()
        count = await _prune_missing_sources(
            manifest=manifest,
            writer=writer,
            namespace="ns-1",
            scope=_SCOPE_KEY,
            present_sources={"a.md"},
        )

        assert count == 1
        assert writer.deleted == [(["b.md-0"], "ns-1")]
        manifest.remove.assert_awaited_once_with("b.md", "ns-1", _SCOPE_KEY)
