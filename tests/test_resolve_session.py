"""Tests for the CLI's ``resolve_session`` helper.

``resolve_session`` is the single chokepoint for "bootstrap orchid +
resolve auth + warm per-user MCP caches" — every chat / mcp / index
command goes through it.  We assert: both layers are invoked,
``warm_for_user`` failures don't abort the command, and bootstrap
exceptions DO surface (they signal a real problem).
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchid_ai.core.state import OrchidAuthContext
from orchid_ai.mcp.session_warmer import OrchidWarmReport

from orchid_cli.commands import _session as session_module


def _fake_orchid(*, warm_raises: Exception | None = None) -> MagicMock:
    fake = MagicMock()
    fake.session_warmer = MagicMock()
    if warm_raises is not None:
        fake.session_warmer.warm_for_user = AsyncMock(side_effect=warm_raises)
    else:
        fake.session_warmer.warm_for_user = AsyncMock(return_value=OrchidWarmReport())
    fake.close = AsyncMock()
    return fake


def _fake_auth() -> OrchidAuthContext:
    return OrchidAuthContext(access_token="t", tenant_key="cli", user_id="cli-user")


@pytest.mark.asyncio
async def test_resolve_session_invokes_both_layers():
    fake = _fake_orchid()
    auth = _fake_auth()
    with (
        patch.object(session_module, "bootstrap", new=AsyncMock(return_value=fake)),
        patch.object(session_module, "get_auth_context", new=AsyncMock(return_value=auth)),
    ):
        orchid, resolved_auth = await session_module.resolve_session("config.yml")
    assert orchid is fake
    assert resolved_auth is auth
    fake.session_warmer.warm_for_user.assert_awaited_once_with(auth)


@pytest.mark.asyncio
async def test_resolve_session_swallows_warm_failure(caplog):
    fake = _fake_orchid(warm_raises=RuntimeError("upstream unreachable"))
    auth = _fake_auth()
    with (
        patch.object(session_module, "bootstrap", new=AsyncMock(return_value=fake)),
        patch.object(session_module, "get_auth_context", new=AsyncMock(return_value=auth)),
        caplog.at_level(logging.WARNING, logger="orchid_cli.commands._session"),
    ):
        # Returns normally — the warm error is logged, not raised.
        orchid, resolved_auth = await session_module.resolve_session("config.yml")
    assert orchid is fake
    assert resolved_auth is auth
    assert any("warm-up raised" in m for m in caplog.messages)


@pytest.mark.asyncio
async def test_resolve_session_propagates_bootstrap_failure():
    """Bootstrap raising signals a real config problem — surface it."""
    with (
        patch.object(
            session_module,
            "bootstrap",
            new=AsyncMock(side_effect=FileNotFoundError("missing.yml")),
        ),
        patch.object(session_module, "get_auth_context", new=AsyncMock()),
        pytest.raises(FileNotFoundError),
    ):
        await session_module.resolve_session("missing.yml")


@pytest.mark.asyncio
async def test_session_context_closes_orchid_on_exit():
    fake = _fake_orchid()
    auth = _fake_auth()
    with (
        patch.object(session_module, "bootstrap", new=AsyncMock(return_value=fake)),
        patch.object(session_module, "get_auth_context", new=AsyncMock(return_value=auth)),
    ):
        async with session_module.session_context("config.yml") as (orchid, resolved_auth):
            assert orchid is fake
            assert resolved_auth is auth
        fake.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_context_closes_orchid_after_exception():
    fake = _fake_orchid()
    auth = _fake_auth()
    with (
        patch.object(session_module, "bootstrap", new=AsyncMock(return_value=fake)),
        patch.object(session_module, "get_auth_context", new=AsyncMock(return_value=auth)),
    ):
        with pytest.raises(RuntimeError):
            async with session_module.session_context("config.yml"):
                raise RuntimeError("oops")
    # close still called even when the body raised.
    fake.close.assert_awaited_once()
