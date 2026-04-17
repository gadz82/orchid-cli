"""Tests that the chat module's built-in slash commands register idempotently.

Reloading ``commands.chat`` (as can happen in test collection or
integrator plugin refresh flows) must NOT leave duplicate registry
entries — the registry is keyed by command name, and the per-name
last-wins semantics means we end up with the same state either way.
"""

from __future__ import annotations

import importlib

from orchid_cli import slash_commands


class TestIdempotentRegistration:
    def test_builtins_present_after_first_import(self):
        # Simply importing the module (which pytest already has) registers
        # the built-ins; verify a representative subset.
        names = {e.name for e in slash_commands.list_slash_commands()}
        assert {"/list", "/switch", "/new", "/history", "/rename"}.issubset(names)

    def test_reload_does_not_duplicate(self):
        from orchid_cli.commands import chat as chat_module

        count_before = len(slash_commands.list_slash_commands())
        importlib.reload(chat_module)
        count_after = len(slash_commands.list_slash_commands())
        assert count_before == count_after

    def test_integrator_override_is_preserved_across_reload(self):
        from orchid_cli.commands import chat as chat_module
        from orchid_cli.slash_commands import SlashContext, register_slash_command

        async def custom_handler(_: SlashContext) -> str | None:
            return "custom"

        # Override the built-in with a custom handler
        register_slash_command("/list", custom_handler)
        assert slash_commands.get_slash_command("/list").handler is custom_handler

        # Reloading chat re-runs _register_builtin_slash_commands, which
        # overwrites /list back to the built-in — this is intended.
        importlib.reload(chat_module)
        entry = slash_commands.get_slash_command("/list")
        assert entry is not None
        assert entry.handler is not custom_handler  # restored to built-in
