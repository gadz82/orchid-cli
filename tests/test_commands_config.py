"""Tests for orchid_cli.commands.config — YAML validation."""
from __future__ import annotations

import tempfile
import os

import yaml
from typer.testing import CliRunner

from orchid_cli.main import app

runner = CliRunner()


class TestConfigValidate:
    def test_valid_config(self):
        """Valid agents.yaml passes validation."""
        config = {
            "version": "1",
            "agents": {
                "test_agent": {
                    "description": "A test agent",
                    "prompt": "You are a test agent.",
                },
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            result = runner.invoke(app, ["config", "validate", f.name])
        os.unlink(f.name)
        assert result.exit_code == 0
        assert "Valid" in result.output
        assert "1 agent(s)" in result.output

    def test_invalid_config_missing_description(self):
        """Missing required field raises validation error."""
        config = {
            "version": "1",
            "agents": {
                "bad_agent": {"prompt": "missing description"},
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            result = runner.invoke(app, ["config", "validate", f.name])
        os.unlink(f.name)
        assert result.exit_code == 1
        assert "Invalid" in result.output

    def test_nonexistent_file(self):
        """Non-existent file path raises error."""
        result = runner.invoke(app, ["config", "validate", "/nonexistent.yaml"])
        assert result.exit_code == 1

    def test_multiple_agents(self):
        """Config with multiple agents shows count."""
        config = {
            "version": "1",
            "agents": {
                "agent_a": {"description": "A", "prompt": "a"},
                "agent_b": {"description": "B", "prompt": "b"},
                "agent_c": {"description": "C", "prompt": "c"},
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            result = runner.invoke(app, ["config", "validate", f.name])
        os.unlink(f.name)
        assert result.exit_code == 0
        assert "3 agent(s)" in result.output

    def test_config_with_supervisor(self):
        """Config with supervisor shows assistant name."""
        config = {
            "version": "1",
            "supervisor": {"assistant_name": "TestBot"},
            "agents": {
                "agent": {"description": "d", "prompt": "p"},
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config, f)
            f.flush()
            result = runner.invoke(app, ["config", "validate", f.name])
        os.unlink(f.name)
        assert result.exit_code == 0
        assert "TestBot" in result.output
