"""Tests for orchid_cli.bootstrap — config loading and YAML overlay."""

from __future__ import annotations

import os
import tempfile

import yaml

from orchid_ai.config.yaml_env import YAML_TO_ENV
from orchid_cli.bootstrap import _apply_yaml_to_env


class TestApplyYamlToEnv:
    def test_missing_file_is_silent(self):
        """Missing YAML file doesn't raise."""
        _apply_yaml_to_env("/nonexistent/path.yml")  # should not raise

    def test_applies_llm_settings(self):
        config = {"llm": {"model": "openai/gpt-4o"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            os.environ.pop("LITELLM_MODEL", None)
            _apply_yaml_to_env(f.name)
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
            _apply_yaml_to_env(f.name)
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
            _apply_yaml_to_env(f.name)
            assert os.environ["LITELLM_MODEL"] == "keep-this"
        os.unlink(f.name)
        os.environ.pop("LITELLM_MODEL", None)

    def test_agents_config_path_applied(self):
        config = {"agents": {"config_path": "my/agents.yaml"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            os.environ.pop("AGENTS_CONFIG_PATH", None)
            _apply_yaml_to_env(f.name)
            assert os.environ.get("AGENTS_CONFIG_PATH") == "my/agents.yaml"
        os.unlink(f.name)


class TestYamlToEnvMapping:
    def test_storage_keys_present(self):
        """Storage keys exist in mapping (even though they're skipped at runtime)."""
        assert ("storage", "class") in YAML_TO_ENV
        assert ("storage", "dsn") in YAML_TO_ENV

    def test_agents_key_present(self):
        assert ("agents", "config_path") in YAML_TO_ENV
