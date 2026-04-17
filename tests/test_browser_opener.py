"""Tests for the injected ``browser_opener`` seam in OAuth PKCE flows.

Verifies that the user-login ``run_login_flow`` and the lower-level
``run_pkce_flow`` both launch the browser via the injected callable
(not ``webbrowser.open`` directly) — the lever tests and headless CI
use to avoid a real browser.
"""

from __future__ import annotations

import pytest

from orchid_cli.auth.config import OAuthProviderConfig
from orchid_cli.auth.flow import run_login_flow
from orchid_cli.auth.pkce import run_pkce_flow


class TestLoginFlowBrowserInjection:
    @pytest.mark.asyncio
    async def test_browser_opener_called_with_auth_url(self):
        opened: list[str] = []

        def fake_opener(url: str) -> bool:
            opened.append(url)
            return True

        config = OAuthProviderConfig(
            client_id="test-client",
            scopes="openid",
            authorization_endpoint="https://auth.example/authorize",
            token_endpoint="https://auth.example/token",
        )

        # Tight timeout — we only care that the URL is passed, not the
        # full callback round-trip (which would need a real browser).
        with pytest.raises(RuntimeError, match="timeout"):
            await run_login_flow(config, timeout=0.3, browser_opener=fake_opener)

        assert len(opened) == 1
        assert opened[0].startswith("https://auth.example/authorize?")
        assert "client_id=test-client" in opened[0]
        assert "code_challenge=" in opened[0]


class TestMcpPkceBrowserInjection:
    @pytest.mark.asyncio
    async def test_browser_opener_called_with_authorize_url(self):
        opened: list[str] = []

        def fake_opener(url: str) -> bool:
            opened.append(url)
            return True

        # Tight timeout so we don't block on the callback.
        result = await run_pkce_flow(
            auth_endpoint="https://idp.example/authorize",
            token_endpoint="https://idp.example/token",
            client_id="mcp-client",
            scopes="read",
            timeout=0.3,
            browser_opener=fake_opener,
        )

        assert result.success is False  # timeout / no callback — expected
        assert len(opened) == 1
        assert opened[0].startswith("https://idp.example/authorize?")
        assert "client_id=mcp-client" in opened[0]
