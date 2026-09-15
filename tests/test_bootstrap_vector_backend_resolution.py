"""Bootstrap vector-backend resolution from ``orchid.yml``.

Precedence under test: explicit flag → env var → orchid.yml
(``cli_rag:`` wins over ``rag:``) → CLI default (chroma).  A backend
declared only in YAML is probed for reachability and falls back to
chroma when unreachable; explicit flag / env intent is never probed.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import yaml

from orchid_cli import bootstrap as bootstrap_module
from orchid_cli.bootstrap import DEFAULT_VECTOR_BACKEND, bootstrap


def _make_mock_orchid():
    """Build a mock Orchid that satisfies bootstrap's post-construction reads."""
    orchid = AsyncMock()
    orchid.runtime.default_model = "test-model"
    orchid.config = MagicMock()
    orchid.config.agents = {"agent-a": MagicMock()}
    orchid.warm_unauthenticated_capabilities = AsyncMock(return_value=MagicMock(warmed=0, skipped=0, failed=0))
    return orchid


def _write_config(tmp_path, data: dict) -> str:
    path = tmp_path / "orchid.yml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return str(path)


async def _bootstrap_with(config_path: str, **kwargs):
    with patch("orchid_cli.bootstrap.Orchid.from_config_path", new_callable=AsyncMock) as mock_from_config:
        mock_from_config.return_value = _make_mock_orchid()
        await bootstrap(config_path, **kwargs)
        return mock_from_config


class TestYamlBackendResolution:
    async def test_yaml_rag_backend_used_when_reachable(self, tmp_path, monkeypatch):
        monkeypatch.delenv("VECTOR_BACKEND", raising=False)
        monkeypatch.delenv("CHROMA_PATH", raising=False)
        config_path = _write_config(tmp_path, {"rag": {"vector_backend": "qdrant"}})

        with patch.object(bootstrap_module, "_check_backend_available", return_value=True) as probe:
            mock_from_config = await _bootstrap_with(config_path)

        probe.assert_called_once_with("qdrant", qdrant_url="http://localhost:6333")
        assert os.environ.get("VECTOR_BACKEND") == "qdrant"
        _, kwargs = mock_from_config.call_args
        assert kwargs["vector_backend"] == "qdrant"

    async def test_yaml_backend_falls_back_to_chroma_when_unreachable(self, tmp_path, monkeypatch):
        monkeypatch.delenv("VECTOR_BACKEND", raising=False)
        monkeypatch.delenv("CHROMA_PATH", raising=False)
        config_path = _write_config(tmp_path, {"rag": {"vector_backend": "qdrant"}})

        with patch.object(bootstrap_module, "_check_backend_available", return_value=False):
            mock_from_config = await _bootstrap_with(config_path)

        assert os.environ.get("VECTOR_BACKEND") == DEFAULT_VECTOR_BACKEND
        _, kwargs = mock_from_config.call_args
        assert kwargs["vector_backend"] == DEFAULT_VECTOR_BACKEND

    async def test_yaml_qdrant_url_used_for_probe(self, tmp_path, monkeypatch):
        monkeypatch.delenv("VECTOR_BACKEND", raising=False)
        monkeypatch.delenv("CHROMA_PATH", raising=False)
        monkeypatch.delenv("QDRANT_URL", raising=False)
        config_path = _write_config(tmp_path, {"rag": {"vector_backend": "qdrant"}})

        with patch.object(bootstrap_module, "_check_backend_available", return_value=True) as probe:
            await _bootstrap_with(config_path, qdrant_url="http://custom:6333")

        probe.assert_called_once_with("qdrant", qdrant_url="http://custom:6333")

    async def test_cli_rag_wins_over_rag(self, tmp_path, monkeypatch):
        monkeypatch.delenv("VECTOR_BACKEND", raising=False)
        monkeypatch.delenv("CHROMA_PATH", raising=False)
        config_path = _write_config(
            tmp_path,
            {"rag": {"vector_backend": "qdrant"}, "cli_rag": {"vector_backend": "chroma"}},
        )

        with patch.object(bootstrap_module, "_check_backend_available", return_value=True) as probe:
            mock_from_config = await _bootstrap_with(config_path)

        probe.assert_called_once_with("chroma", qdrant_url="http://localhost:6333")
        _, kwargs = mock_from_config.call_args
        assert kwargs["vector_backend"] == "chroma"

    async def test_empty_cli_rag_skips_rag_and_uses_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("VECTOR_BACKEND", raising=False)
        monkeypatch.delenv("CHROMA_PATH", raising=False)
        config_path = _write_config(tmp_path, {"rag": {"vector_backend": "qdrant"}, "cli_rag": {}})

        with patch.object(bootstrap_module, "_check_backend_available", return_value=True) as probe:
            mock_from_config = await _bootstrap_with(config_path)

        probe.assert_called_once_with(DEFAULT_VECTOR_BACKEND, qdrant_url="http://localhost:6333")
        _, kwargs = mock_from_config.call_args
        assert kwargs["vector_backend"] == DEFAULT_VECTOR_BACKEND


class TestExplicitBackendSkipsProbe:
    async def test_flag_skips_probe(self, monkeypatch):
        monkeypatch.delenv("VECTOR_BACKEND", raising=False)
        monkeypatch.delenv("CHROMA_PATH", raising=False)

        with patch.object(bootstrap_module, "_check_backend_available", return_value=False) as probe:
            mock_from_config = await _bootstrap_with("/fake/config.yml", vector_backend="qdrant")

        probe.assert_not_called()
        _, kwargs = mock_from_config.call_args
        assert kwargs["vector_backend"] == "qdrant"

    async def test_env_var_skips_probe(self, monkeypatch):
        monkeypatch.delenv("CHROMA_PATH", raising=False)
        monkeypatch.setenv("VECTOR_BACKEND", "qdrant")

        with patch.object(bootstrap_module, "_check_backend_available", return_value=False) as probe:
            mock_from_config = await _bootstrap_with("/fake/config.yml")

        probe.assert_not_called()
        _, kwargs = mock_from_config.call_args
        assert kwargs["vector_backend"] == "qdrant"
