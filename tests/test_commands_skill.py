"""Tests for orchid_cli.commands.skill — Claude Code skill generation."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import yaml
from typer.testing import CliRunner

from orchid_cli.main import app

runner = CliRunner()


def _write_config(config: dict) -> str:
    """Write a YAML config to a temp file, return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    yaml.dump(config, f)
    f.flush()
    f.close()
    return f.name


def _minimal_config(**overrides: object) -> dict:
    """Return a minimal valid agents.yaml dict."""
    base = {
        "version": "1",
        "agents": {
            "helper": {
                "description": "A helpful assistant",
                "prompt": "You are a helpful assistant.",
            },
        },
    }
    base.update(overrides)
    return base


class TestSkillGenerate:
    def test_generates_agent_skill(self, tmp_path):
        """Single agent generates SKILL.md."""
        cfg_path = _write_config(_minimal_config())
        out = str(tmp_path / "skills")
        result = runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        assert result.exit_code == 0
        assert (tmp_path / "skills" / "helper" / "SKILL.md").exists()

    def test_skill_md_contains_prompt(self, tmp_path):
        """SKILL.md includes the agent's system prompt."""
        cfg_path = _write_config(_minimal_config())
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        content = (tmp_path / "skills" / "helper" / "SKILL.md").read_text()
        assert "You are a helpful assistant." in content

    def test_skill_md_has_frontmatter(self, tmp_path):
        """SKILL.md has YAML frontmatter with name and description."""
        cfg_path = _write_config(_minimal_config())
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        content = (tmp_path / "skills" / "helper" / "SKILL.md").read_text()
        assert content.startswith("---\n")
        assert "name: helper" in content
        assert "description:" in content

    def test_generates_scripts_dir(self, tmp_path):
        """Agent with built-in tools gets a scripts/ directory."""
        config = _minimal_config(
            tools={
                "my_tool": {
                    "handler": "orchid_ai.tools.math.calculate_completion_rate",
                    "description": "Calculate completion rate",
                },
            },
        )
        config["agents"]["helper"]["tools"] = ["my_tool"]
        cfg_path = _write_config(config)
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        scripts_dir = tmp_path / "skills" / "helper" / "scripts"
        assert scripts_dir.exists()
        # Should have a .py file
        py_files = list(scripts_dir.glob("*.py"))
        assert len(py_files) >= 1

    def test_no_scripts_without_tools(self, tmp_path):
        """Agent without tools does not generate scripts/ directory."""
        cfg_path = _write_config(_minimal_config())
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        assert not (tmp_path / "skills" / "helper" / "scripts").exists()

    def test_script_is_executable(self, tmp_path):
        """Generated tool script can be executed with python."""
        config = _minimal_config(
            tools={
                "calc_rate": {
                    "handler": "orchid_ai.tools.math.calculate_completion_rate",
                    "description": "Calc rate",
                },
            },
        )
        config["agents"]["helper"]["tools"] = ["calc_rate"]
        cfg_path = _write_config(config)
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        script = tmp_path / "skills" / "helper" / "scripts" / "math.py"
        assert script.exists()
        # Run the script
        result = subprocess.run(
            [sys.executable, str(script), "calculate_completion_rate", "--enrolled", "100", "--completed", "75"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "75.0" in result.stdout

    def test_script_help_flag(self, tmp_path):
        """Generated script responds to --help."""
        config = _minimal_config(
            tools={
                "calc_rate": {
                    "handler": "orchid_ai.tools.math.calculate_completion_rate",
                    "description": "Calc rate",
                },
            },
        )
        config["agents"]["helper"]["tools"] = ["calc_rate"]
        cfg_path = _write_config(config)
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        script = tmp_path / "skills" / "helper" / "scripts" / "math.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "calculate_completion_rate" in result.stdout

    def test_skill_md_references_scripts(self, tmp_path):
        """SKILL.md references scripts/ with execution commands."""
        config = _minimal_config(
            tools={
                "calc_rate": {
                    "handler": "orchid_ai.tools.math.calculate_completion_rate",
                    "description": "Calc rate",
                },
            },
        )
        config["agents"]["helper"]["tools"] = ["calc_rate"]
        cfg_path = _write_config(config)
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        content = (tmp_path / "skills" / "helper" / "SKILL.md").read_text()
        assert "scripts/math.py" in content
        assert "CLAUDE_SKILL_DIR" in content
        assert "allowed-tools" in content

    def test_generates_orchestrator_skill(self, tmp_path):
        """Orchestrator skill generates its own SKILL.md."""
        config = _minimal_config(
            skills={
                "full_workflow": {
                    "description": "End-to-end workflow",
                    "steps": [
                        {"agent": "helper", "instruction": "Do the thing"},
                    ],
                },
            },
        )
        cfg_path = _write_config(config)
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        skill_md = tmp_path / "skills" / "full_workflow" / "SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text()
        assert "End-to-end workflow" in content
        assert "Do the thing" in content

    def test_include_filter(self, tmp_path):
        """--include filters which agents/skills are generated."""
        config = {
            "version": "1",
            "agents": {
                "alpha": {"description": "Agent A", "prompt": "A"},
                "beta": {"description": "Agent B", "prompt": "B"},
            },
        }
        cfg_path = _write_config(config)
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out, "--include", "alpha"])
        os.unlink(cfg_path)
        assert (tmp_path / "skills" / "alpha" / "SKILL.md").exists()
        assert not (tmp_path / "skills" / "beta").exists()

    def test_skips_existing_without_overwrite(self, tmp_path):
        """Existing skill dirs are skipped without --overwrite."""
        cfg_path = _write_config(_minimal_config())
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        result = runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        assert "Skipped" in result.output

    def test_overwrite_flag(self, tmp_path):
        """--overwrite regenerates existing skill dirs."""
        cfg_path = _write_config(_minimal_config())
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        result = runner.invoke(app, ["skill", "generate", cfg_path, "-o", out, "--overwrite"])
        os.unlink(cfg_path)
        assert "Generated" in result.output
        assert "Skipped" not in result.output

    def test_invalid_config_exits_with_error(self):
        """Invalid config path exits with code 1."""
        result = runner.invoke(app, ["skill", "generate", "/nonexistent.yaml"])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_agent_skill_workflows_documented(self, tmp_path):
        """Agent-level skills appear as workflows in SKILL.md."""
        config = _minimal_config(
            tools={
                "step_a": {"handler": "orchid_ai.tools.math.calculate_completion_rate", "description": "Step A"},
            },
        )
        config["agents"]["helper"]["tools"] = ["step_a"]
        config["agents"]["helper"]["skills"] = {
            "my_workflow": {
                "description": "A two-step workflow",
                "steps": [
                    {"tool": "step_a", "source": "builtin"},
                ],
            },
        }
        cfg_path = _write_config(config)
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        content = (tmp_path / "skills" / "helper" / "SKILL.md").read_text()
        assert "my_workflow" in content
        assert "A two-step workflow" in content
        # Workflow steps should reference scripts
        assert "scripts/math.py" in content

    def test_mcp_servers_noted(self, tmp_path):
        """MCP servers are documented as non-portable integrations."""
        config = _minimal_config()
        config["agents"]["helper"]["mcp_servers"] = [
            {
                "name": "my-mcp",
                "url": "http://localhost:8080",
                "tools": [{"name": "mcp_tool"}],
            },
        ]
        cfg_path = _write_config(config)
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        content = (tmp_path / "skills" / "helper" / "SKILL.md").read_text()
        assert "my-mcp" in content
        assert "Orchid Runtime Required" in content

    def test_tools_grouped_by_module(self, tmp_path):
        """Tools from the same module share one script file."""
        config = _minimal_config(
            tools={
                "tool_a": {"handler": "orchid_ai.tools.math.calculate_completion_rate", "description": "A"},
                "tool_b": {"handler": "orchid_ai.tools.dates.format_date", "description": "B"},
            },
        )
        config["agents"]["helper"]["tools"] = ["tool_a", "tool_b"]
        cfg_path = _write_config(config)
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        scripts_dir = tmp_path / "skills" / "helper" / "scripts"
        # Two different modules -> two script files
        assert (scripts_dir / "math.py").exists()
        assert (scripts_dir / "dates.py").exists()

    def test_generates_zip_archive(self, tmp_path):
        """--zip flag creates a zip archive of all generated skills."""
        cfg_path = _write_config(_minimal_config())
        out = str(tmp_path / "skills")
        result = runner.invoke(app, ["skill", "generate", cfg_path, "-o", out, "--zip"])
        os.unlink(cfg_path)
        assert result.exit_code == 0
        zip_file = tmp_path / "skills.zip"
        assert zip_file.exists()
        assert zip_file.stat().st_size > 0

    def test_global_guardrails_in_agent_skill(self, tmp_path):
        """Global guardrails appear in agent SKILL.md."""
        config = _minimal_config()
        config["guardrails"] = {
            "input": [
                {"type": "prompt_injection", "fail_action": "block"},
                {"type": "max_length", "fail_action": "block", "config": {"max_characters": 5000}},
            ],
            "output": [
                {"type": "pii_detection", "fail_action": "redact", "config": {"entities": ["email", "phone"]}},
            ],
        }
        cfg_path = _write_config(config)
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        content = (tmp_path / "skills" / "helper" / "SKILL.md").read_text()
        assert "## Guardrails" in content
        assert "### Input Rules" in content
        assert "### Output Rules" in content
        assert "prompt_injection" in content
        assert "max_length" in content
        assert "Max characters: 5000" in content
        assert "pii_detection" in content
        assert "Entities: email, phone" in content

    def test_per_agent_guardrails_in_skill(self, tmp_path):
        """Per-agent guardrails appear in agent SKILL.md."""
        config = _minimal_config()
        config["agents"]["helper"]["guardrails"] = {
            "input": [
                {
                    "type": "topic_restriction",
                    "fail_action": "warn",
                    "config": {"allowed_topics": ["cooking", "recipes"]},
                },
            ],
        }
        cfg_path = _write_config(config)
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        content = (tmp_path / "skills" / "helper" / "SKILL.md").read_text()
        assert "## Guardrails" in content
        assert "topic_restriction" in content
        assert "Allowed topics: cooking, recipes" in content

    def test_combined_global_and_agent_guardrails(self, tmp_path):
        """Global + per-agent guardrails are merged in SKILL.md."""
        config = _minimal_config()
        config["guardrails"] = {
            "input": [{"type": "prompt_injection", "fail_action": "block"}],
        }
        config["agents"]["helper"]["guardrails"] = {
            "input": [
                {"type": "topic_restriction", "fail_action": "warn", "config": {"allowed_topics": ["sports"]}},
            ],
        }
        cfg_path = _write_config(config)
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        content = (tmp_path / "skills" / "helper" / "SKILL.md").read_text()
        # Both global and per-agent guardrails should be present
        assert "prompt_injection" in content
        assert "topic_restriction" in content

    def test_no_guardrails_section_when_none(self, tmp_path):
        """No ## Guardrails section when no guardrails configured."""
        cfg_path = _write_config(_minimal_config())
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        content = (tmp_path / "skills" / "helper" / "SKILL.md").read_text()
        assert "## Guardrails" not in content

    def test_global_guardrails_in_orchestrator_skill(self, tmp_path):
        """Global guardrails appear in orchestrator SKILL.md."""
        config = _minimal_config(
            skills={
                "workflow": {
                    "description": "A workflow",
                    "steps": [{"agent": "helper", "instruction": "Do it"}],
                },
            },
        )
        config["guardrails"] = {
            "input": [{"type": "content_safety", "fail_action": "block"}],
            "output": [{"type": "pii_detection", "fail_action": "redact"}],
        }
        cfg_path = _write_config(config)
        out = str(tmp_path / "skills")
        runner.invoke(app, ["skill", "generate", cfg_path, "-o", out])
        os.unlink(cfg_path)
        content = (tmp_path / "skills" / "workflow" / "SKILL.md").read_text()
        assert "## Guardrails" in content
        assert "content_safety" in content
        assert "pii_detection" in content
