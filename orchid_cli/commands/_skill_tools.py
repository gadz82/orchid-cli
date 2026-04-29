"""Built-in tool script generation for Claude Code skills.

Builds executable Python scripts that wrap each tool function and emit
a JSON result on stdout. One script per source module, with a CLI
dispatcher that picks the requested tool and coerces parameter types
based on the function signature.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

from orchid_ai.config.schema import OrchidAgentConfig, OrchidAgentsConfig, OrchidBuiltinToolConfig
from orchid_ai.config.tool_registry import list_tools, load_tools_from_config

from ._tool_metadata import ToolMetadataSource, default_source


class ToolScriptInfo:
    """Metadata about a generated tool script."""

    __slots__ = ("script_name", "usage_hint", "parameters")

    def __init__(self, script_name: str, usage_hint: str, parameters: dict[str, str]) -> None:
        self.script_name = script_name
        self.usage_hint = usage_hint
        self.parameters = parameters


# Shared source — registry-first, then inspect-based.  Overridable in
# tests by assigning a different :class:`ToolMetadataSource`.
_tool_metadata_source: ToolMetadataSource = default_source()


def set_metadata_source(source: ToolMetadataSource) -> None:
    """Swap the metadata source used by :func:`generate_tool_scripts` (tests only)."""
    global _tool_metadata_source
    _tool_metadata_source = source


def generate_tool_scripts(
    skill_dir: Path,
    agent_cfg: OrchidAgentConfig,
    config: OrchidAgentsConfig,
) -> dict[str, ToolScriptInfo]:
    """Generate executable Python scripts for each built-in tool.

    Groups tools from the same source module into a single script file.
    Returns a mapping of tool_name -> :class:`ToolScriptInfo`.

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

    _ensure_tools_registered(config)

    module_tools: dict[str, list[tuple[str, OrchidBuiltinToolConfig]]] = {}
    for tool_name in tool_names:
        tool_cfg = config.tools.get(tool_name)
        if not tool_cfg:
            continue
        module_path = tool_cfg.handler.rsplit(".", 1)[0]
        module_tools.setdefault(module_path, []).append((tool_name, tool_cfg))

    result: dict[str, ToolScriptInfo] = {}

    for module_path, tools_in_module in module_tools.items():
        source = _read_module_source(module_path)
        if source is None:
            continue

        module_short_name = module_path.rsplit(".", 1)[-1]
        script_name = f"{module_short_name}.py"

        cli_wrapper = _build_cli_wrapper(tools_in_module)
        clean_source = _strip_future_annotations(source)

        script_content = (
            '"""Auto-generated tool script from Orchid agent configuration."""\n'
            "from __future__ import annotations\n\n"
            f"{clean_source}\n\n"
            f"{cli_wrapper}\n"
        )

        (scripts_dir / script_name).write_text(script_content, encoding="utf-8")

        for tool_name, tool_cfg in tools_in_module:
            func_name = tool_cfg.handler.rsplit(".", 1)[1]
            params = _get_tool_parameters(tool_name, module_path, func_name)
            usage_hint = _build_usage_hint(func_name, params)
            result[tool_name] = ToolScriptInfo(
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
    """Build a CLI usage hint like '--player_name "<player_name>"'."""
    if not params:
        return func_name
    args = " ".join(f'--{name} "<{name}>"' for name in params)
    return f"{func_name} {args}"


def _build_cli_wrapper(tools_in_module: list[tuple[str, OrchidBuiltinToolConfig]]) -> str:
    """Build a __main__ CLI wrapper that dispatches to tool functions."""
    func_entries: list[tuple[str, str]] = []
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
