"""Tests for MD config integration with orchid-cli."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from orchid_cli.bootstrap import apply_cli_config


class TestApplyCliConfigMD:
    def test_md_file_skipped_does_not_set_env(self, tmp_path: Path):
        """apply_cli_config skips .md files — no env vars set from YAML."""
        config = {"llm": {"model": "should-not-apply"}}
        config_file = tmp_path / "config.md"
        config_file.write_text(yaml.dump(config))
        os.environ.pop("LITELLM_MODEL", None)
        apply_cli_config(str(config_file))
        assert "LITELLM_MODEL" not in os.environ

    def test_yml_file_not_skipped(self, tmp_path: Path):
        """apply_cli_config processes .yml files."""
        config = {"llm": {"model": "test-model"}}
        config_file = tmp_path / "config.yml"
        config_file.write_text(yaml.dump(config))
        os.environ.pop("LITELLM_MODEL", None)
        apply_cli_config(str(config_file))
        assert os.environ.get("LITELLM_MODEL") == "test-model"

    def test_yaml_file_not_skipped(self, tmp_path: Path):
        """apply_cli_config processes .yaml files."""
        config = {"llm": {"model": "yaml-model"}}
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config))
        os.environ.pop("LITELLM_MODEL", None)
        apply_cli_config(str(config_file))
        assert os.environ.get("LITELLM_MODEL") == "yaml-model"
