"""Tests for ChromaDB metadata filter translation."""

from __future__ import annotations

import pytest

from orchid_cli.rag.backends.chroma import _translate_metadata_filter


class TestTranslateMetadataFilter:
    def test_exact_match(self):
        result = _translate_metadata_filter({"status": "published"})
        assert result == {"status": {"$eq": "published"}}

    def test_match_any(self):
        result = _translate_metadata_filter({"language": ["en", "fr"]})
        assert result == {"language": {"$in": ["en", "fr"]}}

    def test_range_gte(self):
        result = _translate_metadata_filter({"view_count": {"gte": 100}})
        assert result == {"view_count": {"$gte": 100}}

    def test_range_gte_lte(self):
        result = _translate_metadata_filter({"view_count": {"gte": 10, "lte": 100}})
        assert result == {"view_count": {"$gte": 10, "$lte": 100}}

    def test_range_gt_lt(self):
        result = _translate_metadata_filter({"score": {"gt": 0.5, "lt": 1.0}})
        assert result == {"score": {"$gt": 0.5, "$lt": 1.0}}

    def test_negation(self):
        result = _translate_metadata_filter({"deprecated": {"not": True}})
        assert result == {"deprecated": {"$ne": True}}

    def test_contains_warns_and_skips(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            result = _translate_metadata_filter({"tags": {"contains": "alpha"}})
        assert result is None
        assert "not supported" in caplog.text
        assert "tags" in caplog.text

    def test_backend_namespaced_skipped(self):
        result = _translate_metadata_filter({"_qdrant": {"raw": "value"}})
        assert result is None

    def test_scope_keys_skipped(self):
        result = _translate_metadata_filter(
            {
                "tenant_id": "T",
                "scope": "tenant",
                "user_id": "U",
                "chat_id": "C",
                "agent_id": "A",
                "status": "published",
            }
        )
        assert result == {"status": {"$eq": "published"}}

    def test_multiple_conditions(self):
        result = _translate_metadata_filter(
            {
                "status": "published",
                "language": ["en", "fr"],
                "view_count": {"gte": 100},
            }
        )
        assert result == {
            "$and": [
                {"status": {"$eq": "published"}},
                {"language": {"$in": ["en", "fr"]}},
                {"view_count": {"$gte": 100}},
            ]
        }

    def test_empty_dict_returns_none(self):
        result = _translate_metadata_filter({})
        assert result is None

    def test_none_input_returns_none(self):
        result = _translate_metadata_filter(None)  # type: ignore[arg-type]
        assert result is None

    def test_unknown_operator_raises(self):
        with pytest.raises(ValueError, match="Unknown metadata filter operator"):
            _translate_metadata_filter({"field": {"unknown": "value"}})
