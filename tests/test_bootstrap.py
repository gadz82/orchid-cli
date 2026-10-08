"""Tests for orchid_cli.bootstrap — config loading and YAML overlay."""

from __future__ import annotations

import os
import tempfile

import pytest
import yaml
from orchid_ai.config.yaml_env import YAML_TO_ENV

from orchid_cli.bootstrap import _has_cli_rag_section, apply_cli_config


class TestApplyYamlToEnv:
    def test_missing_file_is_silent(self):
        """Missing YAML file doesn't raise."""
        apply_cli_config("/nonexistent/path.yml")  # should not raise

    def test_applies_llm_settings(self):
        config = {"llm": {"model": "openai/gpt-4o"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            os.environ.pop("LITELLM_MODEL", None)
            apply_cli_config(f.name)
            assert os.environ.get("LITELLM_MODEL") == "openai/gpt-4o"
        os.unlink(f.name)

    def test_skips_storage_section(self):
        """Storage settings from YAML are skipped (CLI has its own defaults)."""
        config = {
            "storage": {"class": "should.not.apply", "dsn": "/docker/path.db"},
            "llm": {"model": "test-model"},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            os.environ.pop("CHAT_STORAGE_CLASS", None)
            os.environ.pop("CHAT_DB_DSN", None)
            os.environ.pop("LITELLM_MODEL", None)
            apply_cli_config(f.name)
            # Storage should NOT be set
            assert "CHAT_STORAGE_CLASS" not in os.environ
            assert "CHAT_DB_DSN" not in os.environ
            # But LLM should be set
            assert os.environ.get("LITELLM_MODEL") == "test-model"
        os.unlink(f.name)

    def test_env_overrides_yaml(self):
        config = {"llm": {"model": "should-not-apply"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            os.environ["LITELLM_MODEL"] = "keep-this"
            apply_cli_config(f.name)
            assert os.environ["LITELLM_MODEL"] == "keep-this"
        os.unlink(f.name)
        os.environ.pop("LITELLM_MODEL", None)

    def test_agents_config_path_applied(self):
        config = {"agents": {"config_path": "my/agents.yaml"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            os.environ.pop("AGENTS_CONFIG_PATH", None)
            apply_cli_config(f.name)
            assert os.environ.get("AGENTS_CONFIG_PATH") == "my/agents.yaml"
        os.unlink(f.name)


class TestYamlToEnvMapping:
    def test_storage_keys_present(self):
        """Storage keys exist in mapping (even though they're skipped at runtime)."""
        assert ("storage", "class") in YAML_TO_ENV
        assert ("storage", "dsn") in YAML_TO_ENV

    def test_agents_key_present(self):
        assert ("agents", "config_path") in YAML_TO_ENV

    def test_cli_rag_keys_present(self):
        """cli_rag keys exist in mapping."""
        assert ("cli_rag", "vector_backend") in YAML_TO_ENV
        assert ("cli_rag", "embedding_model") in YAML_TO_ENV


class TestCliRagOverride:
    """Tests for cli_rag: section overriding rag: section."""

    def test_cli_rag_overrides_rag_section(self):
        """When both rag: and cli_rag: exist, cli_rag: values win."""
        config = {
            "rag": {
                "vector_backend": "qdrant",
                "qdrant_url": "http://qdrant:6333",
                "embedding_model": "gemini/gemini-embedding-001",
            },
            "cli_rag": {
                "vector_backend": "chroma",
                "embedding_model": "ollama/nomic-embed-text",
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            os.environ.pop("VECTOR_BACKEND", None)
            os.environ.pop("QDRANT_URL", None)
            os.environ.pop("EMBEDDING_MODEL", None)
            apply_cli_config(f.name)
            # cli_rag values should win
            assert os.environ.get("VECTOR_BACKEND") == "chroma"
            assert os.environ.get("EMBEDDING_MODEL") == "ollama/nomic-embed-text"
            # QDRANT_URL should NOT be set (rag: was skipped)
            assert "QDRANT_URL" not in os.environ
        os.unlink(f.name)

    def test_cli_rag_absent_falls_back_to_rag(self):
        """When cli_rag: is absent, rag: values are used."""
        config = {
            "rag": {
                "vector_backend": "qdrant",
                "qdrant_url": "http://qdrant:6333",
                "embedding_model": "text-embedding-3-small",
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            os.environ.pop("VECTOR_BACKEND", None)
            os.environ.pop("QDRANT_URL", None)
            os.environ.pop("EMBEDDING_MODEL", None)
            apply_cli_config(f.name)
            # rag values should be used
            assert os.environ.get("VECTOR_BACKEND") == "qdrant"
            assert os.environ.get("QDRANT_URL") == "http://qdrant:6333"
            assert os.environ.get("EMBEDDING_MODEL") == "text-embedding-3-small"
        os.unlink(f.name)

    def test_cli_rag_empty_dict_is_not_active(self):
        """An empty cli_rag: dict is not considered active."""
        config = {
            "rag": {"vector_backend": "qdrant"},
            "cli_rag": {},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            os.environ.pop("VECTOR_BACKEND", None)
            apply_cli_config(f.name)
            # Empty cli_rag: is still a dict, so rag: should be skipped
            # But since cli_rag has no values, VECTOR_BACKEND won't be set
            # This is expected behavior — empty cli_rag: means "use CLI defaults"
            assert "VECTOR_BACKEND" not in os.environ
        os.unlink(f.name)

    def test_cli_rag_non_dict_is_ignored(self):
        """A non-dict cli_rag: value is ignored (rag: is used)."""
        config = {
            "rag": {"vector_backend": "qdrant"},
            "cli_rag": "invalid",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            os.environ.pop("VECTOR_BACKEND", None)
            apply_cli_config(f.name)
            # cli_rag is not a dict, so rag: should be used
            assert os.environ.get("VECTOR_BACKEND") == "qdrant"
        os.unlink(f.name)


class TestHasCliRagSection:
    """Tests for _has_cli_rag_section helper."""

    def test_returns_true_when_cli_rag_present(self):
        config = {"cli_rag": {"vector_backend": "chroma"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            assert _has_cli_rag_section(f.name) is True
        os.unlink(f.name)

    def test_returns_false_when_cli_rag_absent(self):
        config = {"rag": {"vector_backend": "qdrant"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            assert _has_cli_rag_section(f.name) is False
        os.unlink(f.name)

    def test_returns_false_for_non_dict(self):
        config = {"cli_rag": "not a dict"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            assert _has_cli_rag_section(f.name) is False
        os.unlink(f.name)

    def test_returns_false_for_missing_file(self):
        assert _has_cli_rag_section("/nonexistent/path.yml") is False

    def test_returns_true_for_empty_dict(self):
        """An empty cli_rag: dict is still considered active."""
        config = {"cli_rag": {}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            assert _has_cli_rag_section(f.name) is True
        os.unlink(f.name)


class TestBootstrapStorageDefaults:
    """``bootstrap()`` must pass durable SQLite defaults to the framework.

    Regression: after the SQLite extraction the framework default became
    in-memory; ``bootstrap()`` previously delegated to it and silently
    lost durability (CLI chats/config/MCP state did not survive restarts).
    """

    _ENV_VARS = (
        "CHAT_STORAGE_CLASS",
        "CHAT_DB_DSN",
        "MCP_TOKEN_STORE_CLASS",
        "MCP_CLIENT_REGISTRATION_STORE_CLASS",
        "MCP_GATEWAY_STATE_STORE_CLASS",
        "VECTOR_BACKEND",
    )

    @staticmethod
    def _write_config(tmp_path) -> str:
        config = tmp_path / "orchid.yml"
        config.write_text("agents:\n  config_path: agents.yaml\n", encoding="utf-8")
        return str(config)

    @staticmethod
    def _dummy_orchid():
        from unittest.mock import AsyncMock, MagicMock

        dummy = MagicMock()
        dummy.warm_unauthenticated_capabilities = AsyncMock(return_value=MagicMock(warmed=0, skipped=0, failed=0))
        dummy.runtime.default_model = "test-model"
        dummy.config.agents = {}
        return dummy

    @pytest.mark.asyncio
    async def test_passes_sqlite_defaults_when_unconfigured(self, monkeypatch, tmp_path):
        from unittest.mock import AsyncMock, patch

        from orchid_ai import Orchid

        from orchid_cli import bootstrap as bootstrap_module

        for var in self._ENV_VARS:
            monkeypatch.delenv(var, raising=False)

        dummy = self._dummy_orchid()
        with patch.object(Orchid, "from_config_path", new=AsyncMock(return_value=dummy)) as from_cfg:
            await bootstrap_module.bootstrap(self._write_config(tmp_path))

        kwargs = from_cfg.call_args.kwargs
        assert kwargs["chat_storage_class"] == bootstrap_module.DEFAULT_STORAGE_CLASS
        assert kwargs["chat_db_dsn"] == bootstrap_module.DEFAULT_STORAGE_DSN
        assert kwargs["mcp_token_store_class"] == bootstrap_module.DEFAULT_TOKEN_STORE_CLASS
        assert kwargs["mcp_client_registration_store_class"] == bootstrap_module.DEFAULT_REGISTRATION_STORE_CLASS
        assert kwargs["mcp_gateway_state_store_class"] == bootstrap_module.DEFAULT_GATEWAY_STATE_STORE_CLASS
        assert kwargs["mcp_token_store_dsn"] == bootstrap_module.DEFAULT_STORAGE_DSN

    @pytest.mark.asyncio
    async def test_env_overrides_storage_defaults(self, monkeypatch, tmp_path):
        from unittest.mock import AsyncMock, patch

        from orchid_ai import Orchid

        from orchid_cli import bootstrap as bootstrap_module

        for var in self._ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("CHAT_STORAGE_CLASS", "custom_pkg.storage.ChatStorage")
        monkeypatch.setenv("MCP_TOKEN_STORE_CLASS", "custom_pkg.storage.TokenStore")

        dummy = self._dummy_orchid()
        with patch.object(Orchid, "from_config_path", new=AsyncMock(return_value=dummy)) as from_cfg:
            await bootstrap_module.bootstrap(self._write_config(tmp_path))

        kwargs = from_cfg.call_args.kwargs
        assert kwargs["chat_storage_class"] == "custom_pkg.storage.ChatStorage"
        assert kwargs["mcp_token_store_class"] == "custom_pkg.storage.TokenStore"
        # Unset keys still get the CLI defaults.
        assert kwargs["mcp_gateway_state_store_class"] == bootstrap_module.DEFAULT_GATEWAY_STATE_STORE_CLASS
