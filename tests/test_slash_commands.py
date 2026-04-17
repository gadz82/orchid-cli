"""Tests for the slash-command registry."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from orchid_cli.slash_commands import (
    SlashContext,
    clear_slash_commands,
    get_slash_command,
    list_slash_commands,
    register_slash_command,
    unregister_slash_command,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts with an empty registry."""
    clear_slash_commands()
    yield
    clear_slash_commands()


@dataclass
class _FakeConsole:
    written: list[str]

    def print(self, *args, **_):
        self.written.extend(str(a) for a in args)


def _ctx(arg: str = "") -> SlashContext:
    return SlashContext(
        ctx=object(),
        arg=arg,
        current_chat_id="chat-xyz",
        auth=object(),
        console=_FakeConsole(written=[]),
    )


class TestRegistration:
    @pytest.mark.asyncio
    async def test_register_and_lookup(self):
        async def handler(_: SlashContext) -> str | None:
            return None

        register_slash_command("/foo", handler, help="foo cmd")
        entry = get_slash_command("/foo")

        assert entry is not None
        assert entry.name == "/foo"
        assert entry.handler is handler
        assert entry.help == "foo cmd"

    @pytest.mark.asyncio
    async def test_register_adds_leading_slash(self):
        async def h(_: SlashContext) -> str | None:
            return None

        register_slash_command("bar", h)
        assert get_slash_command("bar") is not None
        assert get_slash_command("/bar") is not None

    @pytest.mark.asyncio
    async def test_last_registration_wins(self):
        async def first(_: SlashContext) -> str | None:
            return "first"

        async def second(_: SlashContext) -> str | None:
            return "second"

        register_slash_command("/x", first)
        register_slash_command("/x", second)

        result = await get_slash_command("/x").handler(_ctx())
        assert result == "second"

    def test_unregister_removes(self):
        async def h(_: SlashContext) -> str | None:
            return None

        register_slash_command("/gone", h)
        unregister_slash_command("/gone")
        assert get_slash_command("/gone") is None

    def test_unregister_missing_is_noop(self):
        unregister_slash_command("/never-registered")  # must not raise

    def test_list_is_sorted(self):
        async def h(_: SlashContext) -> str | None:
            return None

        register_slash_command("/zeta", h)
        register_slash_command("/alpha", h)
        register_slash_command("/mu", h)

        names = [e.name for e in list_slash_commands()]
        assert names == ["/alpha", "/mu", "/zeta"]


class TestHandlerContract:
    @pytest.mark.asyncio
    async def test_context_fields_propagate(self):
        seen: dict = {}

        async def h(sc: SlashContext) -> str | None:
            seen["arg"] = sc.arg
            seen["current"] = sc.current_chat_id
            return None

        register_slash_command("/echo", h)
        await get_slash_command("/echo").handler(_ctx(arg="banana"))

        assert seen == {"arg": "banana", "current": "chat-xyz"}

    @pytest.mark.asyncio
    async def test_handler_returns_new_chat_id(self):
        async def h(_: SlashContext) -> str | None:
            return "brand-new-chat"

        register_slash_command("/new", h)
        result = await get_slash_command("/new").handler(_ctx())
        assert result == "brand-new-chat"
