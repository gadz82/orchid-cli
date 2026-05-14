"""Tests for MD config integration with orchid-cli."""

from __future__ import annotations

import os
import tempfile

import yaml

from orchid_cli.bootstrap import apply_cli_config


class TestApplyCliConfigMD:
    def test_md_file_skipped_does_not_set_env(self):
        """apply_cli_config skips .md files — no env vars set from YAML."""
        config = {"llm": {"model": "should-not-apply"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            os.environ.pop("LITELLM_MODEL", None)
            apply_cli_config(f.name)
            assert "LITELLM_MODEL" not in os.environ
        os.unlink(f.name)

    def test_yml_file_not_skipped(self):
        """apply_cli_config processes .yml files."""
        config = {"llm": {"model": "test-model"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            os.environ.pop("LITELLM_MODEL", None)
            apply_cli_config(f.name)
            assert os.environ.get("LITELLM_MODEL") == "test-model"
        os.unlink(f.name)

    def test_yaml_file_not_skipped(self):
        """apply_cli_config processes .yaml files."""
        config = {"llm": {"model": "yaml-model"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            os.environ.pop("LITELLM_MODEL", None)
            apply_cli_config(f.name)
            assert os.environ.get("LITELLM_MODEL") == "yaml-model"
        os.unlink(f.name)
