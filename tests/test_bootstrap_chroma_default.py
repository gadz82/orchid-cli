"""Tests that bootstrap() sets ChromaDB defaults correctly."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

from orchid_cli.bootstrap import DEFAULT_CHROMA_PATH, DEFAULT_VECTOR_BACKEND, bootstrap


def _make_mock_orchid():
    """Build a mock Orchid that satisfies bootstrap's post-construction reads."""
    orchid = AsyncMock()
    orchid.runtime.default_model = "test-model"
    orchid.config = MagicMock()
    orchid.config.agents = {"agent-a": MagicMock()}
    orchid.warm_unauthenticated_capabilities = AsyncMock(return_value=MagicMock(warmed=0, skipped=0, failed=0))
    return orchid


class TestBootstrapChromaDefault:
    async def test_sets_vector_backend_default(self):
        os.environ.pop("VECTOR_BACKEND", None)
        os.environ.pop("CHROMA_PATH", None)

        with patch("orchid_cli.bootstrap.Orchid.from_config_path", new_callable=AsyncMock) as mock_from_config:
            mock_from_config.return_value = _make_mock_orchid()
            await bootstrap("/fake/config.yml")

            assert os.environ.get("VECTOR_BACKEND") == DEFAULT_VECTOR_BACKEND
            assert os.environ.get("CHROMA_PATH") == DEFAULT_CHROMA_PATH
            mock_from_config.assert_awaited_once()
            _, kwargs = mock_from_config.call_args
            assert kwargs["vector_backend"] == DEFAULT_VECTOR_BACKEND

    async def test_explicit_vector_backend_override(self):
        os.environ.pop("VECTOR_BACKEND", None)
        os.environ.pop("CHROMA_PATH", None)

        with patch("orchid_cli.bootstrap.Orchid.from_config_path", new_callable=AsyncMock) as mock_from_config:
            mock_from_config.return_value = _make_mock_orchid()
            await bootstrap("/fake/config.yml", vector_backend="qdrant")

            assert os.environ.get("VECTOR_BACKEND") == "qdrant"
            _, kwargs = mock_from_config.call_args
            assert kwargs["vector_backend"] == "qdrant"

    async def test_explicit_chroma_path_override(self):
        os.environ.pop("VECTOR_BACKEND", None)
        os.environ.pop("CHROMA_PATH", None)

        with patch("orchid_cli.bootstrap.Orchid.from_config_path", new_callable=AsyncMock) as mock_from_config:
            mock_from_config.return_value = _make_mock_orchid()
            await bootstrap("/fake/config.yml", chroma_path="/custom/chroma")

            assert os.environ.get("CHROMA_PATH") == "/custom/chroma"

    async def test_env_var_override(self):
        os.environ["VECTOR_BACKEND"] = "qdrant"
        os.environ["CHROMA_PATH"] = "/env/chroma"

        with patch("orchid_cli.bootstrap.Orchid.from_config_path", new_callable=AsyncMock) as mock_from_config:
            mock_from_config.return_value = _make_mock_orchid()
            await bootstrap("/fake/config.yml")

            _, kwargs = mock_from_config.call_args
            assert kwargs["vector_backend"] == "qdrant"
            assert os.environ.get("CHROMA_PATH") == "/env/chroma"

        os.environ.pop("VECTOR_BACKEND", None)
        os.environ.pop("CHROMA_PATH", None)
