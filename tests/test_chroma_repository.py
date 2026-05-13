"""Integration tests for ChromaRepository against a temporary PersistentClient."""

from __future__ import annotations

import tempfile

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from orchid_ai.core.scopes import OrchidRAGScope
from orchid_cli.rag.backends.chroma import ChromaRepository


class FakeEmbeddings(Embeddings):
    """Deterministic fake embeddings for tests.

    All vectors are identical so every query matches every document
    (distance == 0).  This keeps tests focused on plumbing rather
    than embedding quality.
    """

    def __init__(self, dimension: int = 4):
        self.dimension = dimension
        self._vec = [0.42] * dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)


@pytest.fixture
def repo():
    with tempfile.TemporaryDirectory() as tmpdir:
        embeddings = FakeEmbeddings(dimension=4)
        r = ChromaRepository(
            path=tmpdir,
            embeddings=embeddings,
            embedding_dimension=4,
        )
        yield r


@pytest.fixture
def sample_docs():
    return [
        Document(id="doc-1", page_content="hello world", metadata={"tenant_id": "T", "scope": "tenant"}),
        Document(id="doc-2", page_content="foo bar", metadata={"tenant_id": "T", "user_id": "U", "scope": "user"}),
        Document(
            id="doc-3",
            page_content="baz qux",
            metadata={"tenant_id": "T", "user_id": "U", "chat_id": "C", "scope": "chat_shared"},
        ),
    ]


class TestIndexAndRetrieve:
    async def test_index_and_retrieve(self, repo, sample_docs):
        await repo.index(sample_docs, namespace="test_ns")
        # With tenant-only scope we see shared + tenant-level data.
        # sample_docs has doc-1 at tenant scope; doc-2 at user scope;
        # doc-3 at chat_shared scope — only doc-1 matches tenant-level.
        scope = OrchidRAGScope(tenant_id="T")
        results = await repo.retrieve("hello", namespace="test_ns", k=10, scope=scope)
        assert len(results) == 1
        doc_ids = [r.document.metadata.get("doc_id", "") for r in results]
        assert "doc-1" in doc_ids

    async def test_retrieve_respects_k(self, repo):
        docs = [
            Document(id="doc-1", page_content="hello world", metadata={"tenant_id": "T", "scope": "tenant"}),
            Document(id="doc-2", page_content="foo bar", metadata={"tenant_id": "T", "scope": "tenant"}),
            Document(id="doc-3", page_content="baz qux", metadata={"tenant_id": "T", "scope": "tenant"}),
        ]
        await repo.index(docs, namespace="test_ns")
        scope = OrchidRAGScope(tenant_id="T")
        results = await repo.retrieve("hello", namespace="test_ns", k=2, scope=scope)
        assert len(results) == 2

    async def test_retrieve_without_scope_uses_default_tenant(self, repo):
        docs = [
            Document(id="doc-1", page_content="hello world", metadata={}),
            Document(id="doc-2", page_content="foo bar", metadata={}),
        ]
        await repo.index(docs, namespace="test_ns")
        # No scope passed — should match docs with default tenant
        results = await repo.retrieve("hello", namespace="test_ns", k=10)
        assert len(results) == 2


class TestUpsert:
    async def test_upsert_idempotent(self, repo):
        docs = [
            Document(id="doc-1", page_content="hello world", metadata={"tenant_id": "T", "scope": "tenant"}),
            Document(id="doc-2", page_content="foo bar", metadata={"tenant_id": "T", "scope": "tenant"}),
        ]
        await repo.upsert(docs, namespace="test_ns")
        scope = OrchidRAGScope(tenant_id="T")
        first = await repo.retrieve("hello", namespace="test_ns", k=10, scope=scope)
        await repo.upsert(docs, namespace="test_ns")
        second = await repo.retrieve("hello", namespace="test_ns", k=10, scope=scope)
        assert len(first) == len(second)

    async def test_upsert_updates_content(self, repo):
        docs = [Document(id="doc-1", page_content="original", metadata={})]
        await repo.upsert(docs, namespace="test_ns")
        updated = [Document(id="doc-1", page_content="updated", metadata={})]
        await repo.upsert(updated, namespace="test_ns")
        results = await repo.retrieve("updated", namespace="test_ns", k=1)
        assert results[0].document.page_content == "updated"


class TestDelete:
    async def test_delete_by_id(self, repo):
        docs = [
            Document(id="doc-1", page_content="hello world", metadata={"tenant_id": "T", "scope": "tenant"}),
            Document(id="doc-2", page_content="foo bar", metadata={"tenant_id": "T", "scope": "tenant"}),
        ]
        await repo.index(docs, namespace="test_ns")
        await repo.delete(["doc-1"], namespace="test_ns")
        scope = OrchidRAGScope(tenant_id="T")
        results = await repo.retrieve("hello", namespace="test_ns", k=10, scope=scope)
        doc_ids = [r.document.metadata.get("doc_id", "") for r in results]
        assert "doc-1" not in doc_ids
        assert "doc-2" in doc_ids


class TestScopeFiltering:
    async def test_scope_filter_shared_tenant(self, repo):
        docs = [
            Document(id="d1", page_content="shared", metadata={"tenant_id": "__shared__", "scope": "tenant"}),
            Document(id="d2", page_content="private", metadata={"tenant_id": "T", "scope": "tenant"}),
        ]
        await repo.index(docs, namespace="test_ns")
        scope = OrchidRAGScope(tenant_id="T")
        results = await repo.retrieve("shared", namespace="test_ns", k=10, scope=scope)
        # Should see both __shared__ and tenant-level data
        contents = [r.document.page_content for r in results]
        assert "shared" in contents
        assert "private" in contents

    async def test_scope_filter_tenant_level(self, repo):
        docs = [
            Document(id="d1", page_content="tenant", metadata={"tenant_id": "T", "scope": "tenant"}),
            Document(id="d2", page_content="user", metadata={"tenant_id": "T", "user_id": "U", "scope": "user"}),
        ]
        await repo.index(docs, namespace="test_ns")
        scope = OrchidRAGScope(tenant_id="T")
        results = await repo.retrieve("tenant", namespace="test_ns", k=10, scope=scope)
        contents = [r.document.page_content for r in results]
        assert "tenant" in contents
        # Without user_id in scope, user-level should NOT be visible
        # (it requires user_id match)
        assert "user" not in contents

    async def test_scope_filter_user_level(self, repo):
        docs = [
            Document(id="d1", page_content="user_a", metadata={"tenant_id": "T", "user_id": "A", "scope": "user"}),
            Document(id="d2", page_content="user_b", metadata={"tenant_id": "T", "user_id": "B", "scope": "user"}),
        ]
        await repo.index(docs, namespace="test_ns")
        scope = OrchidRAGScope(tenant_id="T", user_id="A")
        results = await repo.retrieve("user", namespace="test_ns", k=10, scope=scope)
        contents = [r.document.page_content for r in results]
        assert "user_a" in contents
        assert "user_b" not in contents


class TestMetadataFiltering:
    async def test_metadata_filter_exact_match(self, repo):
        docs = [
            Document(id="d1", page_content="alpha", metadata={"status": "published"}),
            Document(id="d2", page_content="beta", metadata={"status": "draft"}),
        ]
        await repo.index(docs, namespace="test_ns")
        results = await repo.retrieve("alpha", namespace="test_ns", k=10, metadata_filters={"status": "published"})
        assert len(results) == 1
        assert results[0].document.page_content == "alpha"

    async def test_metadata_filter_range(self, repo):
        docs = [
            Document(id="d1", page_content="low", metadata={"score": 10}),
            Document(id="d2", page_content="high", metadata={"score": 100}),
        ]
        await repo.index(docs, namespace="test_ns")
        results = await repo.retrieve("high", namespace="test_ns", k=10, metadata_filters={"score": {"gte": 50}})
        assert len(results) == 1
        assert results[0].document.page_content == "high"

    async def test_metadata_filter_match_any(self, repo):
        docs = [
            Document(id="d1", page_content="en", metadata={"lang": "en"}),
            Document(id="d2", page_content="fr", metadata={"lang": "fr"}),
            Document(id="d3", page_content="de", metadata={"lang": "de"}),
        ]
        await repo.index(docs, namespace="test_ns")
        results = await repo.retrieve("en", namespace="test_ns", k=10, metadata_filters={"lang": ["en", "fr"]})
        contents = [r.document.page_content for r in results]
        assert "en" in contents
        assert "fr" in contents
        assert "de" not in contents


class TestAdminOperations:
    async def test_ensure_collections_idempotent(self, repo):
        await repo.ensure_collections(["ns1", "ns2"])
        await repo.ensure_collections(["ns1", "ns2"])
        # No exception means idempotent

    async def test_promote_scope_returns_zero(self, repo):
        result = await repo.promote_scope(namespace="test_ns", source_filter={}, new_scope_fields={})
        assert result == 0

    async def test_lookup_cached_tool_results_returns_none(self, repo):
        result = await repo.lookup_cached_tool_results("ns", OrchidRAGScope(tenant_id="T"), "tool", 0.0)
        assert result is None


class TestPersistence:
    async def test_persistent_path_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            embeddings = FakeEmbeddings(dimension=4)
            repo1 = ChromaRepository(path=tmpdir, embeddings=embeddings, embedding_dimension=4)
            docs = [Document(id="d1", page_content="survive", metadata={})]
            await repo1.index(docs, namespace="test_ns")

            # Simulate process restart by creating a new repo instance
            repo2 = ChromaRepository(path=tmpdir, embeddings=embeddings, embedding_dimension=4)
            results = await repo2.retrieve("survive", namespace="test_ns", k=1)
            assert len(results) == 1
            assert results[0].document.page_content == "survive"
