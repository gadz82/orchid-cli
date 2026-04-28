"""Bootstrap-time MCP capability warm-up.

``bootstrap()`` must invoke ``Orchid.warm_unauthenticated_capabilities``
after the framework is built so ``auth.mode: none`` MCP servers
populate their capability caches before the first chat — even when no
user is authenticated yet.  Failures in the warm-up MUST NOT abort
bootstrap.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchid_ai.mcp.session_warmer import OrchidWarmReport

from orchid_cli import bootstrap as bootstrap_module


def _fake_orchid(report: OrchidWarmReport | Exception) -> MagicMock:
    fake = MagicMock()
    if isinstance(report, Exception):
        fake.warm_unauthenticated_capabilities = AsyncMock(side_effect=report)
    else:
        fake.warm_unauthenticated_capabilities = AsyncMock(return_value=report)
    fake.runtime = MagicMock()
    fake.runtime.default_model = "test-model"
    fake.config = MagicMock()
    fake.config.agents = {}
    return fake


@pytest.mark.asyncio
async def test_bootstrap_invokes_warm_unauthenticated():
    fake = _fake_orchid(OrchidWarmReport(warmed=["local-tool"]))
    with patch.object(
        bootstrap_module.Orchid,
        "from_config_path",
        new=AsyncMock(return_value=fake),
    ):
        result = await bootstrap_module.bootstrap("")
    assert result is fake
    fake.warm_unauthenticated_capabilities.assert_awaited_once()


@pytest.mark.asyncio
async def test_bootstrap_swallows_warm_failures(caplog):
    fake = _fake_orchid(RuntimeError("ollama not running"))
    with (
        patch.object(
            bootstrap_module.Orchid,
            "from_config_path",
            new=AsyncMock(return_value=fake),
        ),
        caplog.at_level(logging.WARNING, logger="orchid_cli.bootstrap"),
    ):
        # Must NOT raise — the CLI should not abort startup on warm failure.
        await bootstrap_module.bootstrap("")
    fake.warm_unauthenticated_capabilities.assert_awaited_once()
    assert any("warm-up raised" in m for m in caplog.messages)
