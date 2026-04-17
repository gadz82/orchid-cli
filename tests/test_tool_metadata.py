"""Tests for ``orchid_cli.commands._tool_metadata`` — tool metadata sources."""

from __future__ import annotations

import pytest

from orchid_ai.config.tool_registry import (
    ToolParameter,
    _REGISTRY,
    register_tool,
)
from orchid_cli.commands._tool_metadata import (
    ChainedToolMetadataSource,
    InspectToolMetadataSource,
    RegistryToolMetadataSource,
    default_source,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    snapshot = dict(_REGISTRY)
    yield
    _REGISTRY.clear()
    _REGISTRY.update(snapshot)


# ── Module-level function used by InspectToolMetadataSource tests ──


def sample_handler(*, player_name: str = "", limit: int = 10, **_kwargs) -> str:
    """Look up a player.

    Parameters
    ----------
    player_name : str
        Full or partial name.
    limit : int
        Maximum rows to return.
    """
    return f"{player_name}:{limit}"


class TestRegistrySource:
    def test_returns_metadata_for_registered_tool(self):
        register_tool(
            "sample",
            sample_handler,
            description="Sample tool",
            parameters={
                "player_name": ToolParameter(
                    name="player_name",
                    type="string",
                    description="Player to look up",
                    required=True,
                ),
            },
        )

        source = RegistryToolMetadataSource()
        result = source.get_parameters("sample", __name__, "sample_handler")

        assert result == {"player_name": "Player to look up"}

    def test_unknown_tool_returns_none(self):
        source = RegistryToolMetadataSource()
        assert source.get_parameters("not-registered", __name__, "sample_handler") is None

    def test_registered_without_params_returns_none(self):
        def noop():
            """No parameters."""
            return None

        register_tool("noop", noop, description="", parameters={})
        source = RegistryToolMetadataSource()
        assert source.get_parameters("noop", __name__, "noop") is None


class TestInspectSource:
    def test_reads_signature_and_docstring(self):
        source = InspectToolMetadataSource()
        result = source.get_parameters("sample", __name__, "sample_handler")

        assert result is not None
        assert "player_name" in result
        assert "limit" in result
        # kwargs is filtered
        assert "kwargs" not in result

    def test_unresolvable_module_returns_none(self):
        source = InspectToolMetadataSource()
        assert source.get_parameters("x", "no.such.module", "fn") is None

    def test_unresolvable_function_returns_none(self):
        source = InspectToolMetadataSource()
        assert source.get_parameters("x", __name__, "no_such_function") is None


class TestChainedSource:
    def test_first_non_none_wins(self):
        class YesSource:
            def get_parameters(self, *_args, **_kw):
                return {"from": "first"}

        class NeverReachedSource:
            def get_parameters(self, *_args, **_kw):  # pragma: no cover — proven by test
                raise AssertionError("should not be called")

        chain = ChainedToolMetadataSource(sources=[YesSource(), NeverReachedSource()])
        assert chain.get_parameters("t", "m", "f") == {"from": "first"}

    def test_walks_past_none(self):
        class NopeSource:
            def get_parameters(self, *_args, **_kw):
                return None

        class YesSource:
            def get_parameters(self, *_args, **_kw):
                return {"ok": "yes"}

        chain = ChainedToolMetadataSource(sources=[NopeSource(), YesSource()])
        assert chain.get_parameters("t", "m", "f") == {"ok": "yes"}

    def test_all_decline_returns_empty_dict(self):
        class NopeSource:
            def get_parameters(self, *_args, **_kw):
                return None

        chain = ChainedToolMetadataSource(sources=[NopeSource(), NopeSource()])
        assert chain.get_parameters("t", "m", "f") == {}

    def test_empty_dict_beats_none(self):
        """A source returning ``{}`` means 'known, no params' — stops the chain."""
        calls: list[str] = []

        class EmptySource:
            def get_parameters(self, *_args, **_kw):
                calls.append("empty")
                return {}

        class ShouldNotRun:
            def get_parameters(self, *_args, **_kw):
                calls.append("fallback")
                return {"should_not": "appear"}

        chain = ChainedToolMetadataSource(sources=[EmptySource(), ShouldNotRun()])
        assert chain.get_parameters("t", "m", "f") == {}
        assert calls == ["empty"]


class TestDefaultSource:
    def test_registry_beats_inspect(self):
        register_tool(
            "sample",
            sample_handler,
            description="sample",
            parameters={
                "player_name": ToolParameter(
                    name="player_name",
                    type="string",
                    description="Registry wins",
                ),
            },
        )
        source = default_source()
        result = source.get_parameters("sample", __name__, "sample_handler")

        # Registry wins — returns just player_name (inspect would also include `limit`)
        assert result == {"player_name": "Registry wins"}

    def test_inspect_fallback_when_registry_misses(self):
        source = default_source()
        result = source.get_parameters("unregistered", __name__, "sample_handler")

        assert "player_name" in result
        assert "limit" in result
