"""
Skill command — generate Claude Code skills from Orchid agent configuration.

Usage:
    orchid skill generate examples/basketball/agents.yaml --output .claude/skills
    orchid skill generate examples/helpdesk/config/agents.yaml -o ./skills --include basketball,psychologist
"""

from __future__ import annotations

import importlib
import inspect
import shutil
from pathlib import Path

import typer
from rich.console import Console

from orchid_ai.config.loader import load_config
from orchid_ai.config.schema import (
    OrchidAgentConfig,
    OrchidAgentsConfig,
    OrchidBuiltinToolConfig,
    OrchidGuardrailRuleConfig,
    OrchidGuardrailsConfig,
    OrchidOrchestratorSkillConfig,
)
from orchid_ai.config.tool_registry import (
    load_tools_from_config,
    list_tools,
)

from ._tool_metadata import ToolMetadataSource, default_source

app = typer.Typer(help="Generate Claude Code skills from Orchid config", no_args_is_help=True)
console = Console()


# ── Public command ────────────────────────────────────────────────


@app.command()
def generate(
    config_path: str = typer.Argument(..., help="Path to agents.yaml config file"),
    output: str = typer.Option(".claude/skills", "-o", "--output", help="Output directory for generated skills"),
    include: str | None = typer.Option(
        None, "--include", help="Comma-separated agent/skill names to include (default: all)"
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing skill directories"),
    zip_archive: bool = typer.Option(False, "--zip", help="Create a zip archive of the generated skills"),
) -> None:
    """Generate Claude Code skill folders from an Orchid agents.yaml configuration."""
    try:
        config = load_config(config_path)
    except Exception as exc:
        console.print(f"[red]Error loading config:[/red] {exc}")
        raise typer.Exit(code=1)

    out_dir = Path(output)
    include_set = {n.strip() for n in include.split(",")} if include else None

    generated: list[str] = []
    skipped: list[str] = []

    # Generate agent skills
    for agent_name, agent_cfg in config.agents.items():
        if include_set and agent_name not in include_set:
            continue
        skill_dir = out_dir / agent_name
        if skill_dir.exists() and not overwrite:
            skipped.append(agent_name)
            continue
        _generate_agent_skill(skill_dir, agent_name, agent_cfg, config)
        generated.append(agent_name)

    # Generate orchestrator skills
    for skill_name, skill_cfg in config.skills.items():
        if include_set and skill_name not in include_set:
            continue
        skill_dir = out_dir / skill_name
        if skill_dir.exists() and not overwrite:
            skipped.append(skill_name)
            continue
        _generate_orchestrator_skill(skill_dir, skill_name, skill_cfg, config)
        generated.append(skill_name)

    # Summary
    if generated:
        console.print(f"\n[green]Generated {len(generated)} skill(s):[/green]")
        for name in generated:
            console.print(f"  [bold]{out_dir / name}/SKILL.md[/bold]")
    if skipped:
        console.print(f"\n[yellow]Skipped {len(skipped)} (already exist, use --overwrite):[/yellow]")
        for name in skipped:
            console.print(f"  {name}")
    if not generated and not skipped:
        console.print("[yellow]No agents or skills matched the filter.[/yellow]")

    # Create zip archive if requested
    if zip_archive and generated:
        zip_path = Path(f"{output.rstrip('/')}.zip")
        shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=out_dir.parent, base_dir=out_dir.name)
        console.print(f"\n[green]Archive created:[/green] [bold]{zip_path}[/bold]")


# ── Agent skill generation ────────────────────────────────────────


def _generate_agent_skill(
    skill_dir: Path,
    agent_name: str,
    agent_cfg: OrchidAgentConfig,
    config: OrchidAgentsConfig,
) -> None:
    """Generate a Claude Code skill directory for one Orchid agent."""
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Generate executable scripts for built-in tools
    tool_scripts = _generate_tool_scripts(skill_dir, agent_cfg, config)

    # Build SKILL.md
    skill_md = _build_agent_skill_md(agent_name, agent_cfg, config, tool_scripts)
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")


def _build_agent_skill_md(
    agent_name: str,
    agent_cfg: OrchidAgentConfig,
    config: OrchidAgentsConfig,
    tool_scripts: dict[str, _ToolScriptInfo],
) -> str:
    """Build the SKILL.md content for an Orchid agent."""
    parts: list[str] = []

    # ── Frontmatter ──
    description = _clean_description(agent_cfg.description)
    allowed: list[str] = []
    if tool_scripts:
        allowed.append("Bash(python *)")
    frontmatter_lines = [
        "---",
        f"name: {agent_name}",
        f'description: "{_truncate(description, 240)}"',
    ]
    if allowed:
        frontmatter_lines.append(f'allowed-tools: "{" ".join(allowed)}"')
    frontmatter_lines.append("---")
    parts.append("\n".join(frontmatter_lines) + "\n")

    # ── Title + origin ──
    parts.append(f"# {agent_name}\n")
    parts.append(
        f"> Auto-generated from Orchid agent configuration. "
        f"This skill replicates the knowledge and instructions of the `{agent_name}` agent.\n"
    )

    # ── Agent system prompt (the core value) ──
    parts.append("## Instructions\n")
    parts.append(agent_cfg.prompt.strip() + "\n")

    # ── Built-in tools as executable scripts ──
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
            # Show usage with the actual parameters
            parts.append(f"```bash\npython ${{CLAUDE_SKILL_DIR}}/scripts/{info.script_name} {info.usage_hint}\n```\n")
            if info.parameters:
                parts.append("**Parameters:**\n")
                for param_name, param_desc in info.parameters.items():
                    parts.append(f"- `{param_name}`: {param_desc}")
                parts.append("")

    # ── MCP servers (informational, not portable) ──
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

    # ── Agent-level skills (workflows) ──
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

    # ── Guardrails ──
    guardrails_md = _build_guardrails_section(config.guardrails, agent_cfg.guardrails, agent_name)
    if guardrails_md:
        parts.append(guardrails_md)

    # ── RAG context note ──
    if agent_cfg.rag.enabled:
        ns = agent_cfg.rag.namespace or agent_name
        parts.append("## RAG Context (Orchid Runtime Required)\n")
        parts.append(
            f"In the Orchid runtime, this agent retrieves contextual documents from "
            f"the `{ns}` namespace (top-{agent_cfg.rag.k} results). "
            f"This capability is not available in the Claude Code skill.\n"
        )

    return "\n".join(parts)


# ── Orchestrator skill generation ─────────────────────────────────


def _generate_orchestrator_skill(
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

    description = _clean_description(skill_cfg.description)
    parts.append(f'---\nname: {skill_name.replace("_", "-")}\ndescription: "{_truncate(description, 240)}"\n---\n')

    parts.append(f"# {skill_name.replace('_', ' ').title()}\n")
    parts.append(
        "> Auto-generated from Orchid orchestrator skill. "
        "This is a multi-agent workflow that coordinates several specialists.\n"
    )

    if skill_cfg.description:
        parts.append("## Purpose\n")
        parts.append(skill_cfg.description.strip() + "\n")

    # ── Workflow steps ──
    parts.append("## Workflow Steps\n")
    parts.append("Execute these steps in order. Each step's output feeds into the next.\n")
    for i, step in enumerate(skill_cfg.steps, 1):
        agent_cfg = config.agents.get(step.agent)
        agent_desc = _clean_description(agent_cfg.description) if agent_cfg else ""
        parts.append(f"### Step {i}: {step.agent}\n")
        if agent_desc:
            parts.append(f"*Agent role: {agent_desc}*\n")
        if step.instruction:
            parts.append(f"**Instruction:** {step.instruction}\n")
        # Include the agent's prompt as context
        if agent_cfg:
            parts.append("<details>\n<summary>Agent system prompt</summary>\n")
            parts.append(f"```\n{agent_cfg.prompt.strip()}\n```\n")
            parts.append("</details>\n")

    # ── Guardrails (global only for orchestrator skills) ──
    guardrails_md = _build_guardrails_section(config.guardrails, None, None)
    if guardrails_md:
        parts.append(guardrails_md)

    # ── Participating agents summary ──
    agent_names = [s.agent for s in skill_cfg.steps]
    parts.append("## Participating Agents\n")
    for name in dict.fromkeys(agent_names):  # unique, preserving order
        agent_cfg = config.agents.get(name)
        if agent_cfg:
            desc = _clean_description(agent_cfg.description)
            parts.append(f"- **{name}**: {desc}")
    parts.append("")

    return "\n".join(parts)


# ── Tool script generation ────────────────────────────────────────


class _ToolScriptInfo:
    """Metadata about a generated tool script."""

    __slots__ = ("script_name", "usage_hint", "parameters")

    def __init__(self, script_name: str, usage_hint: str, parameters: dict[str, str]) -> None:
        self.script_name = script_name
        self.usage_hint = usage_hint
        self.parameters = parameters


def _generate_tool_scripts(
    skill_dir: Path,
    agent_cfg: OrchidAgentConfig,
    config: OrchidAgentsConfig,
) -> dict[str, _ToolScriptInfo]:
    """Generate executable Python scripts for each built-in tool.

    Groups tools from the same source module into a single script file.
    Returns a mapping of tool_name -> _ToolScriptInfo.

    Parameter metadata is sourced from the tool registry (which merges
    YAML-declared parameters with auto-extracted function signatures).
    Falls back to ``inspect``-based extraction when registry data is
    unavailable.
    """
    tool_names = agent_cfg.tools
    if not tool_names:
        return {}

    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    # Ensure tools are registered so we can access their parameters
    _ensure_tools_registered(config)

    # Group tools by source module path
    module_tools: dict[str, list[tuple[str, OrchidBuiltinToolConfig]]] = {}
    for tool_name in tool_names:
        tool_cfg = config.tools.get(tool_name)
        if not tool_cfg:
            continue
        module_path = tool_cfg.handler.rsplit(".", 1)[0]
        module_tools.setdefault(module_path, []).append((tool_name, tool_cfg))

    result: dict[str, _ToolScriptInfo] = {}

    for module_path, tools_in_module in module_tools.items():
        # Read the source file of the module
        source = _read_module_source(module_path)
        if source is None:
            continue

        # Determine script filename from the last part of the module path
        module_short_name = module_path.rsplit(".", 1)[-1]
        script_name = f"{module_short_name}.py"

        # Build the __main__ CLI wrapper
        cli_wrapper = _build_cli_wrapper(tools_in_module)

        # Strip __future__ annotations from source if present (we re-add it)
        clean_source = _strip_future_annotations(source)

        script_content = (
            '"""Auto-generated tool script from Orchid agent configuration."""\n'
            "from __future__ import annotations\n\n"
            f"{clean_source}\n\n"
            f"{cli_wrapper}\n"
        )

        (scripts_dir / script_name).write_text(script_content, encoding="utf-8")

        # Build info for each tool in this module
        for tool_name, tool_cfg in tools_in_module:
            func_name = tool_cfg.handler.rsplit(".", 1)[1]
            params = _get_tool_parameters(tool_name, module_path, func_name)
            usage_hint = _build_usage_hint(func_name, params)
            result[tool_name] = _ToolScriptInfo(
                script_name=script_name,
                usage_hint=usage_hint,
                parameters=params,
            )

    return result


def _ensure_tools_registered(config: OrchidAgentsConfig) -> None:
    """Ensure all built-in tools are loaded into the registry."""
    if config.tools and not list_tools():
        try:
            load_tools_from_config(config.tools)
        except Exception:
            pass  # fall back to inspect-based extraction


# Shared source — registry-first, then inspect-based.  Overridable in
# tests by assigning a different :class:`ToolMetadataSource`.
_tool_metadata_source: ToolMetadataSource = default_source()


def _get_tool_parameters(tool_name: str, module_path: str, func_name: str) -> dict[str, str]:
    """Delegate to the configured :class:`ToolMetadataSource` chain."""
    return _tool_metadata_source.get_parameters(tool_name, module_path, func_name)


def _read_module_source(module_path: str) -> str | None:
    """Read the source code of a Python module by its dotted import path."""
    try:
        module = importlib.import_module(module_path)
        source_file = inspect.getfile(module)
        return Path(source_file).read_text(encoding="utf-8")
    except Exception:
        return None


def _strip_future_annotations(source: str) -> str:
    """Remove 'from __future__ import annotations' to avoid duplication."""
    lines = source.splitlines(keepends=True)
    filtered = []
    for line in lines:
        stripped = line.strip()
        if stripped == "from __future__ import annotations":
            continue
        filtered.append(line)
    return "".join(filtered)


def _build_usage_hint(func_name: str, params: dict[str, str]) -> str:
    """Build a CLI usage hint like '--player_name "LeBron James"'."""
    if not params:
        return func_name
    args = " ".join(f'--{name} "<{name}>"' for name in params)
    return f"{func_name} {args}"


def _build_cli_wrapper(tools_in_module: list[tuple[str, OrchidBuiltinToolConfig]]) -> str:
    """Build a __main__ CLI wrapper that dispatches to tool functions."""
    func_entries: list[tuple[str, str]] = []  # (tool_name, func_name)
    for tool_name, tool_cfg in tools_in_module:
        func_name = tool_cfg.handler.rsplit(".", 1)[1]
        func_entries.append((tool_name, func_name))

    lines: list[str] = []
    lines.append("# ── CLI wrapper (auto-generated) ──────────────────────────────")
    lines.append("")
    lines.append("")
    lines.append("if __name__ == '__main__':")
    lines.append("    import sys")
    lines.append("    import json as _json")
    lines.append("")
    lines.append("    _TOOLS = {")
    for tool_name, func_name in func_entries:
        lines.append(f"        '{func_name}': {func_name},")
    lines.append("    }")
    lines.append("")
    tool_names_str = ", ".join(fn for _, fn in func_entries)
    lines.append("    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):")
    lines.append("        print(f'Usage: python {sys.argv[0]} <tool_name> [--arg value ...]')")
    lines.append(f"        print('Available tools: {tool_names_str}')")
    lines.append("        sys.exit(0)")
    lines.append("")
    lines.append("    _tool_name = sys.argv[1]")
    lines.append("    if _tool_name not in _TOOLS:")
    lines.append("        print(f'Unknown tool: {_tool_name}')")
    lines.append(f"        print('Available tools: {tool_names_str}')")
    lines.append("        sys.exit(1)")
    lines.append("")
    lines.append("    # Parse --key value arguments")
    lines.append("    _kwargs = {}")
    lines.append("    _args = sys.argv[2:]")
    lines.append("    _i = 0")
    lines.append("    while _i < len(_args):")
    lines.append("        if _args[_i].startswith('--') and _i + 1 < len(_args):")
    lines.append("            _kwargs[_args[_i][2:]] = _args[_i + 1]")
    lines.append("            _i += 2")
    lines.append("        else:")
    lines.append("            _i += 1")
    lines.append("")
    lines.append("    # Coerce argument types using function annotations")
    lines.append("    import inspect as _inspect")
    lines.append("    _sig = _inspect.signature(_TOOLS[_tool_name])")
    lines.append("    _coerced = {}")
    lines.append("    for _k, _v in _kwargs.items():")
    lines.append("        _param = _sig.parameters.get(_k)")
    lines.append("        if _param and _param.annotation != _inspect.Parameter.empty:")
    lines.append("            _ann = _param.annotation")
    lines.append("            if _ann in (int, 'int'):")
    lines.append("                _v = int(_v)")
    lines.append("            elif _ann in (float, 'float'):")
    lines.append("                _v = float(_v)")
    lines.append("            elif _ann in (bool, 'bool'):")
    lines.append("                _v = _v.lower() in ('true', '1', 'yes')")
    lines.append("        _coerced[_k] = _v")
    lines.append("")
    lines.append("    _result = _TOOLS[_tool_name](**_coerced)")
    lines.append("    print(_json.dumps(_result, indent=2, default=str))")

    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────


def _build_guardrails_section(
    global_guardrails: OrchidGuardrailsConfig,
    agent_guardrails: OrchidGuardrailsConfig | None,
    agent_name: str | None,
) -> str:
    """Build the ## Guardrails section for a SKILL.md file.

    Combines global guardrails (applied to all agents) with per-agent
    guardrails into human-readable enforcement rules.

    Returns an empty string if no guardrails are configured.
    """
    has_global = global_guardrails.input or global_guardrails.output
    has_agent = agent_guardrails is not None and (agent_guardrails.input or agent_guardrails.output)

    if not has_global and not has_agent:
        return ""

    parts: list[str] = []
    parts.append("## Guardrails\n")
    parts.append(
        "The following safety rules are enforced in the Orchid runtime. "
        "When operating as this skill, you MUST respect these constraints.\n"
    )

    # Collect input and output rules separately
    input_rules: list[OrchidGuardrailRuleConfig] = list(global_guardrails.input)
    output_rules: list[OrchidGuardrailRuleConfig] = list(global_guardrails.output)

    if agent_guardrails is not None:
        input_rules.extend(agent_guardrails.input)
        output_rules.extend(agent_guardrails.output)

    if input_rules:
        parts.append("### Input Rules\n")
        parts.append("These rules apply to user messages BEFORE processing:\n")
        for rule in input_rules:
            parts.append(_format_guardrail_rule(rule))
        parts.append("")

    if output_rules:
        parts.append("### Output Rules\n")
        parts.append("These rules apply to responses BEFORE returning to the user:\n")
        for rule in output_rules:
            parts.append(_format_guardrail_rule(rule))
        parts.append("")

    return "\n".join(parts)


def _format_guardrail_rule(rule: OrchidGuardrailRuleConfig) -> str:
    """Format a single guardrail rule as a readable bullet point."""
    action_labels = {
        "block": "**Block** the message",
        "warn": "**Warn** but allow",
        "redact": "**Redact** matched content",
        "log": "**Log** silently",
    }
    action_desc = action_labels.get(rule.fail_action, f"**{rule.fail_action}**")

    # Build a human-readable description based on the guardrail type
    type_descriptions: dict[str, str] = {
        "prompt_injection": "Prompt injection attempts (instruction overrides, persona hijacks, delimiter injection)",
        "content_safety": "Harmful or unsafe content (violence, self-harm, illegal activity)",
        "pii_detection": "Personally identifiable information (PII)",
        "max_length": "Messages exceeding the character limit",
        "topic_restriction": "Off-topic messages outside allowed domains",
        "groundedness": "Responses not grounded in retrieved context",
    }
    type_desc = type_descriptions.get(rule.type, f"`{rule.type}` guardrail")

    line = f"- **{rule.type}** — {action_desc} if detected: {type_desc}"

    # Append relevant config details
    config_details = _format_guardrail_config(rule.type, rule.config)
    if config_details:
        line += f"\n  {config_details}"

    return line


def _format_guardrail_config(guardrail_type: str, config: dict) -> str:
    """Format guardrail config dict as a readable detail string."""
    if not config:
        return ""

    details: list[str] = []

    if guardrail_type == "pii_detection" and "entities" in config:
        details.append(f"Entities: {', '.join(config['entities'])}")
    if guardrail_type == "max_length" and "max_characters" in config:
        details.append(f"Max characters: {config['max_characters']}")
    if guardrail_type == "topic_restriction" and "allowed_topics" in config:
        details.append(f"Allowed topics: {', '.join(config['allowed_topics'])}")
    if guardrail_type == "content_safety":
        if "categories" in config:
            details.append(f"Categories: {', '.join(config['categories'])}")
        if "blocklist" in config:
            details.append(f"Blocked words: {', '.join(config['blocklist'])}")
    if guardrail_type == "groundedness" and "min_overlap" in config:
        details.append(f"Min overlap: {config['min_overlap']}")

    return "; ".join(details)


def _clean_description(text: str) -> str:
    """Collapse whitespace in a YAML multi-line description."""
    return " ".join(text.split()).strip()


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if needed, escaping quotes for YAML."""
    text = text.replace('"', '\\"')
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"
