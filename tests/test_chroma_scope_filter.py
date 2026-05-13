"""Tests for ChromaDB scope filter translation."""

from __future__ import annotations

from orchid_ai.core.scopes import OrchidRAGScope
from orchid_cli.rag.backends.chroma import _build_chroma_scope_filter


class TestBuildChromaScopeFilter:
    def test_shared_tenant_only(self):
        scope = OrchidRAGScope(tenant_id="T")
        result = _build_chroma_scope_filter(scope)
        assert result == {
            "$or": [
                {"tenant_id": {"$eq": "__shared__"}},
                {"$and": [{"tenant_id": {"$eq": "T"}}, {"scope": {"$eq": "tenant"}}]},
            ]
        }

    def test_user_level(self):
        scope = OrchidRAGScope(tenant_id="T", user_id="U")
        result = _build_chroma_scope_filter(scope)
        assert result == {
            "$or": [
                {"tenant_id": {"$eq": "__shared__"}},
                {"$and": [{"tenant_id": {"$eq": "T"}}, {"scope": {"$eq": "tenant"}}]},
                {
                    "$and": [
                        {"tenant_id": {"$eq": "T"}},
                        {"user_id": {"$eq": "U"}},
                        {"scope": {"$eq": "user"}},
                    ]
                },
            ]
        }

    def test_chat_shared_level(self):
        scope = OrchidRAGScope(tenant_id="T", user_id="U", chat_id="C")
        result = _build_chroma_scope_filter(scope)
        assert result == {
            "$or": [
                {"tenant_id": {"$eq": "__shared__"}},
                {"$and": [{"tenant_id": {"$eq": "T"}}, {"scope": {"$eq": "tenant"}}]},
                {
                    "$and": [
                        {"tenant_id": {"$eq": "T"}},
                        {"user_id": {"$eq": "U"}},
                        {"scope": {"$eq": "user"}},
                    ]
                },
                {
                    "$and": [
                        {"tenant_id": {"$eq": "T"}},
                        {"user_id": {"$eq": "U"}},
                        {"chat_id": {"$eq": "C"}},
                        {"scope": {"$eq": "chat_shared"}},
                    ]
                },
            ]
        }

    def test_chat_agent_level(self):
        scope = OrchidRAGScope(tenant_id="T", user_id="U", chat_id="C", agent_id="A")
        result = _build_chroma_scope_filter(scope)
        assert result == {
            "$or": [
                {"tenant_id": {"$eq": "__shared__"}},
                {"$and": [{"tenant_id": {"$eq": "T"}}, {"scope": {"$eq": "tenant"}}]},
                {
                    "$and": [
                        {"tenant_id": {"$eq": "T"}},
                        {"user_id": {"$eq": "U"}},
                        {"scope": {"$eq": "user"}},
                    ]
                },
                {
                    "$and": [
                        {"tenant_id": {"$eq": "T"}},
                        {"user_id": {"$eq": "U"}},
                        {"chat_id": {"$eq": "C"}},
                        {"scope": {"$eq": "chat_shared"}},
                    ]
                },
                {
                    "$and": [
                        {"tenant_id": {"$eq": "T"}},
                        {"user_id": {"$eq": "U"}},
                        {"chat_id": {"$eq": "C"}},
                        {"agent_id": {"$eq": "A"}},
                        {"scope": {"$eq": "chat_agent"}},
                    ]
                },
            ]
        }

    def test_default_tenant_fallback(self):
        scope = OrchidRAGScope(tenant_id="")
        result = _build_chroma_scope_filter(scope, default_tenant="fallback")
        # The tenant-level clause should use the default tenant
        assert {"$and": [{"tenant_id": {"$eq": "fallback"}}, {"scope": {"$eq": "tenant"}}]} in result["$or"]
