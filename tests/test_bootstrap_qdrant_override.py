"""Tests that explicit Qdrant overrides win over Chroma defaults."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

from orchid_cli.bootstrap import bootstrap


def _make_mock_orchid():
    """Build a mock Orchid that satisfies bootstrap's post-construction reads."""
    orchid = AsyncMock()
    orchid.runtime.default_model = "test-model"
    orchid.config = MagicMock()
    orchid.config.agents = {"agent-a": MagicMock()}
    orchid.warm_unauthenticated_capabilities = AsyncMock(return_value=MagicMock(warmed=0, skipped=0, failed=0))
    return orchid


class TestBootstrapQdrantOverride:
    async def test_vector_backend_arg_overrides_chroma(self):
        os.environ.pop("VECTOR_BACKEND", None)
        os.environ.pop("CHROMA_PATH", None)

        with patch("orchid_cli.bootstrap.Orchid.from_config_path", new_callable=AsyncMock) as mock_from_config:
            mock_from_config.return_value = _make_mock_orchid()
            await bootstrap("/fake/config.yml", vector_backend="qdrant")

            assert os.environ.get("VECTOR_BACKEND") == "qdrant"
            _, kwargs = mock_from_config.call_args
            assert kwargs["vector_backend"] == "qdrant"

    async def test_vector_backend_env_overrides_chroma(self):
        os.environ.pop("VECTOR_BACKEND", None)
        os.environ.pop("CHROMA_PATH", None)
        os.environ["VECTOR_BACKEND"] = "qdrant"

        with patch("orchid_cli.bootstrap.Orchid.from_config_path", new_callable=AsyncMock) as mock_from_config:
            mock_from_config.return_value = _make_mock_orchid()
            await bootstrap("/fake/config.yml")

            _, kwargs = mock_from_config.call_args
            assert kwargs["vector_backend"] == "qdrant"

        os.environ.pop("VECTOR_BACKEND", None)

    async def test_qdrant_url_passed_through(self):
        os.environ.pop("VECTOR_BACKEND", None)
        os.environ.pop("CHROMA_PATH", None)

        with patch("orchid_cli.bootstrap.Orchid.from_config_path", new_callable=AsyncMock) as mock_from_config:
            mock_from_config.return_value = _make_mock_orchid()
            await bootstrap("/fake/config.yml", vector_backend="qdrant", qdrant_url="http://localhost:6333")

            _, kwargs = mock_from_config.call_args
            assert kwargs["qdrant_url"] == "http://localhost:6333"
