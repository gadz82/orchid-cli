"""Tests for orchid_cli.commands.external_agents."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from orchid_cli.main import app

runner = CliRunner()


def _write_config(path: Path, config: dict) -> None:
    with open(path, "w") as f:
        yaml.dump(config, f)


class TestExternalAgentsList:
    def test_lists_configured_external_agents(self, tmp_path: Path):
        config = {
            "version": "1",
            "agents": {
                "orchestrator": {
                    "description": "Lead agent",
                    "prompt": "You are the orchestrator.",
                    "tools": ["ask_cli", "ask_other"],
                },
            },
            "external_agents": {
                "ask_cli": {
                    "command": ["mycli"],
                    "description": "Delegate to mycli",
                    "requires_approval": True,
                    "timeout": 180,
                },
                "ask_other": {
                    "command": ["othercli", "--verbose"],
                    "args": ["--print"],
                    "description": "Delegate to other",
                    "requires_approval": False,
                    "normalizer": "llm",
                },
            },
        }
        config_path = tmp_path / "agents.yaml"
        _write_config(config_path, config)
        result = runner.invoke(app, ["external-agents", "list", str(config_path)])

        assert result.exit_code == 0
        assert "ask_cli" in result.output
        assert "ask_other" in result.output
        assert "mycli" in result.output
        assert "othercli" in result.output

    def test_no_external_agents_configured(self, tmp_path: Path):
        config = {
            "version": "1",
            "agents": {
                "agent": {
                    "description": "A test agent",
                    "prompt": "You are a test agent.",
                },
            },
        }
        config_path = tmp_path / "agents.yaml"
        _write_config(config_path, config)
        result = runner.invoke(app, ["external-agents", "list", str(config_path)])

        assert result.exit_code == 0
        assert "No external agents configured" in result.output

    def test_nonexistent_file(self):
        result = runner.invoke(app, ["external-agents", "list", "/nonexistent/agents.yaml"])
        assert result.exit_code == 1
        assert "File not found" in result.output

    def test_shows_command_and_timeout(self, tmp_path: Path):
        config = {
            "version": "1",
            "agents": {
                "agent": {
                    "description": "d",
                    "prompt": "p",
                },
            },
            "external_agents": {
                "ask_cli": {
                    "command": ["mycli"],
                    "timeout": 300,
                },
            },
        }
        config_path = tmp_path / "agents.yaml"
        _write_config(config_path, config)
        result = runner.invoke(app, ["external-agents", "list", str(config_path)])

        assert result.exit_code == 0
        assert "300" in result.output
