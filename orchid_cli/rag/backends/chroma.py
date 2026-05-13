"""
ChromaDB implementation of OrchidVectorStoreRepository — local, persistent.

Design notes:
- Uses ``chromadb.PersistentClient`` for on-disk storage.
- ``chromadb`` is imported lazily inside ``__init__`` so the module loads
  even when the package isn't installed (graceful degradation).
- Document IDs use the same UUID5 namespace as Qdrant for consistency.
- No sparse/hybrid search in v1 (Chroma doesn't support native sparse vectors).
- No scope promotion in v1 (returns 0 silently).
- Score conversion: Chroma distances → 0–1 score via ``max(0.0, 1.0 - distance)``.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from orchid_ai.core.repository import OrchidSearchResult, OrchidVectorStoreRepository
from orchid_ai.core.scopes import SHARED_TENANT, OrchidRAGScope

logger = logging.getLogger(__name__)

# Stable v5 UUID namespace for point IDs — matches QdrantRepository.
_POINT_ID_NAMESPACE = uuid.UUID("1f23d4a0-2b6e-44b9-9c5c-c2b7e3c8d1e0")

# Backend-namespaced filter prefix.
_BACKEND_NS_PREFIX = "_"

# Operator keys recognised by the metadata-filter mini-language.
_RANGE_OPERATORS = ("gte", "lte", "gt", "lt")


def _build_chroma_scope_filter(scope: OrchidRAGScope, default_tenant: str = "default") -> dict[str, Any]:
    """Build a Chroma ``where`` clause with ``$or`` across all visible scope levels.

    Mirrors ``build_qdrant_filter()`` but produces MongoDB-style operators
    (``$eq``, ``$in``, ``$or``, ``$and``) that Chroma understands.
    """
    tenant_id = scope.tenant_id or default_tenant
    clauses: list[dict[str, Any]] = []

    # 1. Root common — tenant_id = "__shared__"
    clauses.append({"tenant_id": {"$eq": SHARED_TENANT}})

    # 2. Tenant-level — tenant_id = T AND scope = "tenant"
    clauses.append(
        {
            "$and": [
                {"tenant_id": {"$eq": tenant_id}},
                {"scope": {"$eq": "tenant"}},
            ]
        }
    )

    # 3. User-common — requires user_id
    if scope.user_id:
        clauses.append(
            {
                "$and": [
                    {"tenant_id": {"$eq": tenant_id}},
                    {"user_id": {"$eq": scope.user_id}},
                    {"scope": {"$eq": "user"}},
                ]
            }
        )

    # 4. Chat-shared — requires user_id + chat_id
    if scope.user_id and scope.chat_id:
        clauses.append(
            {
                "$and": [
                    {"tenant_id": {"$eq": tenant_id}},
                    {"user_id": {"$eq": scope.user_id}},
                    {"chat_id": {"$eq": scope.chat_id}},
                    {"scope": {"$eq": "chat_shared"}},
                ]
            }
        )

    # 5. Agent-private — requires user_id + chat_id + agent_id
    if scope.user_id and scope.chat_id and scope.agent_id:
        clauses.append(
            {
                "$and": [
                    {"tenant_id": {"$eq": tenant_id}},
                    {"user_id": {"$eq": scope.user_id}},
                    {"chat_id": {"$eq": scope.chat_id}},
                    {"agent_id": {"$eq": scope.agent_id}},
                    {"scope": {"$eq": "chat_agent"}},
                ]
            }
        )

    return {"$or": clauses}


def _translate_metadata_filter(metadata_filters: dict[str, Any]) -> dict[str, Any] | None:
    """Translate the metadata-filter mini-language into a Chroma ``where`` dict.

    Returns ``None`` when the only keys are backend-namespaced or unsupported.
    """
    if not metadata_filters:
        return None

    and_clauses: list[dict[str, Any]] = []

    for key, value in metadata_filters.items():
        if key.startswith(_BACKEND_NS_PREFIX):
            continue

        # Scope keys are handled by the scope filter, not metadata filter.
        if key in ("tenant_id", "scope", "user_id", "chat_id", "agent_id"):
            continue

        if isinstance(value, dict):
            # Range operators
            range_ops = {f"${op}": value[op] for op in _RANGE_OPERATORS if op in value}
            if range_ops:
                and_clauses.append({key: range_ops})
                continue
            if "contains" in value:
                logger.warning("[Chroma] '$contains' operator not supported for key %r; skipping", key)
                continue
            if "not" in value:
                and_clauses.append({key: {"$ne": value["not"]}})
                continue
            raise ValueError(
                f"Unknown metadata filter operator(s) for {key!r}: {sorted(value)}. "
                f"Allowed: gte/lte/gt/lt/contains/not."
            )

        if isinstance(value, list):
            and_clauses.append({key: {"$in": value}})
            continue

        # Scalar exact-match
        and_clauses.append({key: {"$eq": value}})

    if not and_clauses:
        return None
    if len(and_clauses) == 1:
        return and_clauses[0]
    return {"$and": and_clauses}


def _compose_filter(
    scope: OrchidRAGScope | None,
    metadata_filters: dict[str, Any] | None,
    default_tenant: str = "default",
) -> dict[str, Any] | None:
    """Combine scope filter with metadata-filter clauses."""
    if scope is not None:
        scope_filter = _build_chroma_scope_filter(scope, default_tenant)
    else:
        # No scope → only shared data.
        scope_filter = {"tenant_id": {"$in": [default_tenant, SHARED_TENANT]}}

    meta_filter = _translate_metadata_filter(metadata_filters) if metadata_filters else None

    if meta_filter is None:
        return scope_filter

    return {"$and": [scope_filter, meta_filter]}


class ChromaRepository(OrchidVectorStoreRepository):
    """ChromaDB-backed vector store with per-tenant isolation.

    Each ``namespace`` maps to a ChromaDB **collection**.
    Tenant isolation is enforced via a ``tenant_id`` metadata field on every
    document, and all reads filter on the visible scope levels.
    """

    supports_scope_promotion = False

    def __init__(
        self,
        *,
        path: str,
        embeddings: Embeddings,
        embedding_dimension: int = 1536,
        default_tenant: str = "default",
    ):
        import chromadb

        resolved_path = os.path.expanduser(path)
        os.makedirs(resolved_path, exist_ok=True)
        self._client = chromadb.PersistentClient(path=resolved_path)
        self._embeddings = embeddings
        self._embedding_dimension = embedding_dimension
        self._default_tenant = default_tenant
        # Tracks which collections have been verified / created.
        self._verified_collections: set[str] = set()

    # ── OrchidVectorReader ──────────────────────────────────────────

    async def retrieve(
        self,
        query: str,
        namespace: str,
        k: int = 5,
        scope: OrchidRAGScope | None = None,
        metadata_filters: dict[str, object] | None = None,
    ) -> list[OrchidSearchResult]:
        """Retrieve the *k* most relevant documents for *query* in *namespace*."""
        await self._ensure_collection(namespace)

        query_embedding = await self._embeddings.aembed_query(query)
        where_filter = _compose_filter(scope, metadata_filters, self._default_tenant)

        collection = self._client.get_collection(namespace)
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        out: list[OrchidSearchResult] = []
        if not results["ids"]:
            return out

        ids = results["ids"][0]
        documents = results["documents"][0] if results.get("documents") else []
        metadatas = results["metadatas"][0] if results.get("metadatas") else []
        distances = results["distances"][0] if results.get("distances") else []

        for i, doc_id in enumerate(ids):
            content = documents[i] if i < len(documents) else ""
            meta = dict(metadatas[i]) if i < len(metadatas) and metadatas[i] else {}
            distance = distances[i] if i < len(distances) else 0.0
            score = max(0.0, 1.0 - distance)
            out.append(
                OrchidSearchResult(
                    document=Document(
                        id=doc_id,
                        page_content=content,
                        metadata=meta,
                    ),
                    score=score,
                )
            )
        return out

    # ── OrchidVectorWriter ──────────────────────────────────────────

    async def index(
        self,
        documents: list[Document],
        namespace: str,
    ) -> None:
        """Index documents — creates the collection if it doesn't exist."""
        await self._ensure_collection(namespace)

        if not documents:
            return

        texts = [doc.page_content for doc in documents]
        embeddings = await self._embeddings.aembed_documents(texts)

        ids: list[str] = []
        metadatas: list[dict[str, Any]] = []
        chroma_docs: list[str] = []
        chroma_embeddings: list[list[float]] = []

        for i, doc in enumerate(documents):
            doc_id = str(uuid.uuid5(_POINT_ID_NAMESPACE, doc.id or doc.page_content))
            ids.append(doc_id)
            chroma_docs.append(doc.page_content)
            chroma_embeddings.append(embeddings[i])

            meta = dict(doc.metadata)
            meta["doc_id"] = doc.id
            if "tenant_id" not in meta:
                meta["tenant_id"] = self._default_tenant
            metadatas.append(meta)

        collection = self._client.get_collection(namespace)
        collection.add(
            ids=ids,
            documents=chroma_docs,
            metadatas=metadatas,
            embeddings=chroma_embeddings,
        )
        logger.info(
            "[Chroma] indexed %d documents in '%s'",
            len(documents),
            namespace,
        )

    async def upsert(
        self,
        documents: list[Document],
        namespace: str,
    ) -> None:
        """Insert or update documents (idempotent)."""
        await self._ensure_collection(namespace)

        if not documents:
            return

        texts = [doc.page_content for doc in documents]
        embeddings = await self._embeddings.aembed_documents(texts)

        ids: list[str] = []
        metadatas: list[dict[str, Any]] = []
        chroma_docs: list[str] = []
        chroma_embeddings: list[list[float]] = []

        for i, doc in enumerate(documents):
            doc_id = str(uuid.uuid5(_POINT_ID_NAMESPACE, doc.id or doc.page_content))
            ids.append(doc_id)
            chroma_docs.append(doc.page_content)
            chroma_embeddings.append(embeddings[i])

            meta = dict(doc.metadata)
            meta["doc_id"] = doc.id
            if "tenant_id" not in meta:
                meta["tenant_id"] = self._default_tenant
            metadatas.append(meta)

        collection = self._client.get_collection(namespace)
        collection.upsert(
            ids=ids,
            documents=chroma_docs,
            metadatas=metadatas,
            embeddings=chroma_embeddings,
        )
        logger.info(
            "[Chroma] upserted %d documents in '%s'",
            len(documents),
            namespace,
        )

    async def delete(
        self,
        document_ids: list[str],
        namespace: str,
    ) -> None:
        """Remove documents by ID from the namespace."""
        if not document_ids:
            return

        await self._ensure_collection(namespace)
        collection = self._client.get_collection(namespace)

        chroma_ids = [str(uuid.uuid5(_POINT_ID_NAMESPACE, doc_id)) for doc_id in document_ids]
        collection.delete(ids=chroma_ids)
        logger.info(
            "[Chroma] deleted %d documents from '%s'",
            len(document_ids),
            namespace,
        )

    # ── OrchidVectorStoreAdmin ──────────────────────────────────────

    async def ensure_collections(self, namespaces: list[str]) -> None:
        """Pre-create collections at startup (called from lifespan)."""
        for ns in namespaces:
            await self._ensure_collection(ns)

    async def _ensure_collection(self, namespace: str) -> None:
        """Create the collection if missing.

        Chroma collections are created implicitly via ``get_or_create_collection``.
        """
        if namespace in self._verified_collections:
            return
        self._client.get_or_create_collection(
            name=namespace,
            metadata={"dimension": self._embedding_dimension},
        )
        self._verified_collections.add(namespace)
        logger.debug(
            "[Chroma] ensured collection '%s' (dim=%d)",
            namespace,
            self._embedding_dimension,
        )

    # ── Scope promotion ─────────────────────────────────────────────

    async def promote_scope(
        self,
        *,
        namespace: str,
        source_filter: Any,
        new_scope_fields: dict,
    ) -> int:
        """Promote data to a broader scope (e.g. chat → user for sharing).

        Not implemented in v1 — returns 0 silently.
        """
        logger.debug("[Chroma] promote_scope() not implemented — returning 0")
        return 0
