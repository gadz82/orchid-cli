"""Tests for ``OrchidContext.release_resources``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from orchid_cli.bootstrap import OrchidContext


def _ctx_with_bootstrap() -> tuple[OrchidContext, MagicMock]:
    bootstrap = MagicMock()
    bootstrap.runtime = MagicMock()
    bootstrap.runtime.checkpointer = None
    bootstrap.mcp_token_store = AsyncMock()
    bootstrap.chat_repo = AsyncMock()

    ctx = OrchidContext(
        graph=None,
        reader=MagicMock(),
        chat_repo=bootstrap.chat_repo,
        config=MagicMock(),
        model="ollama/llama3.2",
        mcp_token_store=bootstrap.mcp_token_store,
        runtime=bootstrap.runtime,
        _bootstrap=bootstrap,
    )
    return ctx, bootstrap


class TestRelease:
    @pytest.mark.asyncio
    async def test_closes_bootstrap_resources(self):
        ctx, bootstrap = _ctx_with_bootstrap()
        await ctx.release_resources()

        bootstrap.mcp_token_store.close.assert_awaited_once()
        bootstrap.chat_repo.close.assert_awaited_once()
        assert ctx._bootstrap is None

    @pytest.mark.asyncio
    async def test_idempotent(self):
        ctx, _ = _ctx_with_bootstrap()
        await ctx.release_resources()
        # Second call must not raise even though bootstrap is already cleared.
        await ctx.release_resources()

    @pytest.mark.asyncio
    async def test_no_bootstrap_is_noop(self):
        ctx = OrchidContext(
            graph=None,
            reader=MagicMock(),
            chat_repo=MagicMock(),
            config=MagicMock(),
            model="ollama/llama3.2",
        )
        # Must not raise even though _bootstrap was never set.
        await ctx.release_resources()
