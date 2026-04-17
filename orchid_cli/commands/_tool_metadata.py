"""
Tool-parameter metadata — typed source abstraction used by ``skill generate``.

Previously ``_get_tool_parameters`` in ``commands/skill.py`` tried the
registry, silently fell back to ``inspect``, and dict-dived the result.
That hid the resolution order and made it easy to break silently when
the registry shape changed.

Here we split the two sources behind a :class:`ToolMetadataSource`
protocol and expose a :class:`ChainedToolMetadataSource` that walks them
in order — each source returns ``None`` if it has nothing, which makes
"missing" distinguishable from "empty".
"""

from __future__ import annotations

import importlib
import inspect
from typing import Protocol

from orchid_ai.config.tool_registry import find_param_doc


class ToolMetadataSource(Protocol):
    """A provider of ``{param_name: description}`` metadata for a tool."""

    def get_parameters(self, tool_name: str, module_path: str, func_name: str) -> dict[str, str] | None:
        """Return a parameter map, or ``None`` when this source cannot resolve the tool.

        Returning ``{}`` means "known tool, no parameters" — distinct
        from ``None`` which means "unknown to this source, try the next".
        """
        ...


class RegistryToolMetadataSource:
    """Reads parameter metadata from the framework's built-in tool registry."""

    def get_parameters(self, tool_name: str, module_path: str, func_name: str) -> dict[str, str] | None:
        from orchid_ai.config.tool_registry import get_tool

        try:
            entry = get_tool(tool_name)
        except KeyError:
            return None
        if not entry.parameters:
            return None
        return {name: (p.description or p.type) for name, p in entry.parameters.items()}


class InspectToolMetadataSource:
    """Derives parameter metadata from the live function signature + docstring."""

    # Parameters that GenericAgent / build_langchain_tools inject at call
    # time — not part of the user-facing contract.
    _FRAMEWORK_PARAMS = frozenset({"kwargs", "self", "cls"})

    def get_parameters(self, tool_name: str, module_path: str, func_name: str) -> dict[str, str] | None:
        try:
            module = importlib.import_module(module_path)
            func = getattr(module, func_name)
        except (ImportError, AttributeError):
            return None

        try:
            sig = inspect.signature(func)
        except (TypeError, ValueError):
            return None

        docstring = inspect.getdoc(func) or ""

        params: dict[str, str] = {}
        for name, param in sig.parameters.items():
            if name in self._FRAMEWORK_PARAMS:
                continue
            desc = find_param_doc(docstring, name)
            if not desc:
                ann = param.annotation
                desc = str(ann).replace("'", "") if ann is not inspect.Parameter.empty else "string"
            params[name] = desc
        return params


class ChainedToolMetadataSource:
    """Walks several sources in order; first non-``None`` wins.

    ``get_parameters`` returns ``{}`` (not ``None``) when every source
    declines — so the caller can distinguish "known tool, zero params"
    from "unresolvable" should they care.
    """

    def __init__(self, sources: list[ToolMetadataSource]) -> None:
        self._sources = sources

    def get_parameters(self, tool_name: str, module_path: str, func_name: str) -> dict[str, str]:
        for source in self._sources:
            result = source.get_parameters(tool_name, module_path, func_name)
            if result is not None:
                return result
        return {}


def default_source() -> ChainedToolMetadataSource:
    """Registry first, then inspect-based discovery — the canonical chain."""
    return ChainedToolMetadataSource(
        sources=[
            RegistryToolMetadataSource(),
            InspectToolMetadataSource(),
        ]
    )
