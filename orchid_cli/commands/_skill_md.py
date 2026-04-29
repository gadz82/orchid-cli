"""SKILL.md generators for agents and orchestrator skills."""

from __future__ import annotations

from pathlib import Path

from orchid_ai.config.schema import (
    OrchidAgentConfig,
    OrchidAgentsConfig,
    OrchidOrchestratorSkillConfig,
)

from ._skill_guardrails import build_guardrails_section
from ._skill_text import clean_description, truncate
from ._skill_tools import ToolScriptInfo, generate_tool_scripts


def generate_agent_skill(
    skill_dir: Path,
    agent_name: str,
    agent_cfg: OrchidAgentConfig,
    config: OrchidAgentsConfig,
) -> None:
    """Generate a Claude Code skill directory for one Orchid agent."""
    skill_dir.mkdir(parents=True, exist_ok=True)

    tool_scripts = generate_tool_scripts(skill_dir, agent_cfg, config)
    skill_md = _build_agent_skill_md(agent_name, agent_cfg, config, tool_scripts)
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")


def _build_agent_skill_md(
    agent_name: str,
    agent_cfg: OrchidAgentConfig,
    config: OrchidAgentsConfig,
    tool_scripts: dict[str, ToolScriptInfo],
) -> str:
    """Build the SKILL.md content for an Orchid agent."""
    parts: list[str] = []

    # ── Frontmatter ──
    description = clean_description(agent_cfg.description)
    allowed: list[str] = []
    if tool_scripts:
        allowed.append("Bash(python *)")
    frontmatter_lines = [
        "---",
        f"name: {agent_name}",
        f'description: "{truncate(description, 240)}"',
    ]
    if allowed:
        frontmatter_lines.append(f'allowed-tools: "{" ".join(allowed)}"')
    frontmatter_lines.append("---")
    parts.append("\n".join(frontmatter_lines) + "\n")

    parts.append(f"# {agent_name}\n")
    parts.append(
        f"> Auto-generated from Orchid agent configuration. "
        f"This skill replicates the knowledge and instructions of the `{agent_name}` agent.\n"
    )

    parts.append("## Instructions\n")
    parts.append(agent_cfg.prompt.strip() + "\n")

    if tool_scripts:
        parts.append("## Available Tools\n")
        parts.append(
            "This skill includes executable Python scripts for each built-in tool. Run them to get real results.\n"
        )
        for tool_name, info in tool_scripts.items():
            tool_cfg = config.tools.get(tool_name)
            desc = tool_cfg.description if tool_cfg else ""
            parts.append(f"### {tool_name}\n")
            if desc:
                parts.append(f"{desc}\n")
            parts.append(f"```bash\npython ${{CLAUDE_SKILL_DIR}}/scripts/{info.script_name} {info.usage_hint}\n```\n")
            if info.parameters:
                parts.append("**Parameters:**\n")
                for param_name, param_desc in info.parameters.items():
                    parts.append(f"- `{param_name}`: {param_desc}")
                parts.append("")

    if agent_cfg.mcp_servers:
        parts.append("## External Integrations (Orchid Runtime Required)\n")
        parts.append(
            "The following MCP server integrations are available in the Orchid runtime "
            "but cannot be used directly in Claude Code skills.\n"
        )
        for srv in agent_cfg.mcp_servers:
            tool_list = ", ".join(t.name for t in srv.tools) if srv.tools else "(all)"
            parts.append(f"- **{srv.name}** ({srv.transport}): tools = {tool_list}")
        parts.append("")

    if agent_cfg.skills:
        parts.append("## Workflows\n")
        parts.append(
            "The original agent supports these multi-step workflows. "
            "Follow these step sequences when the user's request matches.\n"
        )
        for skill_name, skill_cfg in agent_cfg.skills.items():
            parts.append(f"### {skill_name}\n")
            if skill_cfg.description:
                parts.append(f"{skill_cfg.description.strip()}\n")
            parts.append("**Steps:**\n")
            for i, step in enumerate(skill_cfg.steps, 1):
                if step.tool:
                    info = tool_scripts.get(step.tool)
                    if info:
                        parts.append(
                            f"{i}. Run `python ${{CLAUDE_SKILL_DIR}}/scripts/{info.script_name} {info.usage_hint}`"
                        )
                    else:
                        src = f" (from {step.source})" if step.source else ""
                        parts.append(f"{i}. Call tool `{step.tool}`{src}")
                elif step.agent:
                    parts.append(f"{i}. Delegate to agent `{step.agent}`: {step.instruction}")
            parts.append("")

    guardrails_md = build_guardrails_section(config.guardrails, agent_cfg.guardrails, agent_name)
    if guardrails_md:
        parts.append(guardrails_md)

    if agent_cfg.rag.enabled:
        ns = agent_cfg.rag.namespace or agent_name
        parts.append("## RAG Context (Orchid Runtime Required)\n")
        parts.append(
            f"In the Orchid runtime, this agent retrieves contextual documents from "
            f"the `{ns}` namespace (top-{agent_cfg.rag.k} results). "
            f"This capability is not available in the Claude Code skill.\n"
        )

    return "\n".join(parts)


def generate_orchestrator_skill(
    skill_dir: Path,
    skill_name: str,
    skill_cfg: OrchidOrchestratorSkillConfig,
    config: OrchidAgentsConfig,
) -> None:
    """Generate a Claude Code skill directory for an Orchid orchestrator skill."""
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_md = _build_orchestrator_skill_md(skill_name, skill_cfg, config)
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")


def _build_orchestrator_skill_md(
    skill_name: str,
    skill_cfg: OrchidOrchestratorSkillConfig,
    config: OrchidAgentsConfig,
) -> str:
    """Build the SKILL.md content for an Orchid orchestrator skill."""
    parts: list[str] = []

    description = clean_description(skill_cfg.description)
    parts.append(f'---\nname: {skill_name.replace("_", "-")}\ndescription: "{truncate(description, 240)}"\n---\n')

    parts.append(f"# {skill_name.replace('_', ' ').title()}\n")
    parts.append(
        "> Auto-generated from Orchid orchestrator skill. "
        "This is a multi-agent workflow that coordinates several specialists.\n"
    )

    if skill_cfg.description:
        parts.append("## Purpose\n")
        parts.append(skill_cfg.description.strip() + "\n")

    parts.append("## Workflow Steps\n")
    parts.append("Execute these steps in order. Each step's output feeds into the next.\n")
    for i, step in enumerate(skill_cfg.steps, 1):
        agent_cfg = config.agents.get(step.agent)
        agent_desc = clean_description(agent_cfg.description) if agent_cfg else ""
        parts.append(f"### Step {i}: {step.agent}\n")
        if agent_desc:
            parts.append(f"*Agent role: {agent_desc}*\n")
        if step.instruction:
            parts.append(f"**Instruction:** {step.instruction}\n")
        if agent_cfg:
            parts.append("<details>\n<summary>Agent system prompt</summary>\n")
            parts.append(f"```\n{agent_cfg.prompt.strip()}\n```\n")
            parts.append("</details>\n")

    guardrails_md = build_guardrails_section(config.guardrails, None, None)
    if guardrails_md:
        parts.append(guardrails_md)

    agent_names = [s.agent for s in skill_cfg.steps]
    parts.append("## Participating Agents\n")
    for name in dict.fromkeys(agent_names):  # unique, preserving order
        agent_cfg = config.agents.get(name)
        if agent_cfg:
            desc = clean_description(agent_cfg.description)
            parts.append(f"- **{name}**: {desc}")
    parts.append("")

    return "\n".join(parts)
