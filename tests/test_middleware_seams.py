"""Tests for the injectable seams on ``get_auth_context``.

These prove that ``token_loader`` / ``token_saver`` / ``token_refresher``
can be passed in explicitly, with no monkey-patching required.
"""

from __future__ import annotations

import time

import pytest

from orchid_cli.auth.config import OAuthProviderConfig
from orchid_cli.auth.middleware import get_auth_context
from orchid_cli.auth.token_store import StoredToken


def _cfg() -> OAuthProviderConfig:
    return OAuthProviderConfig(
        client_id="app",
        authorization_endpoint="https://auth.example/authorize",
        token_endpoint="https://auth.example/token",
    )


class TestInjectableSeams:
    @pytest.mark.asyncio
    async def test_token_loader_seam(self):
        fake = StoredToken(
            access_token="injected",
            expires_at=time.time() + 3600,
            tenant_key="t1",
            user_id="u1",
        )

        auth = await get_auth_context(
            "",
            oauth_config=_cfg(),
            token_loader=lambda _: fake,
        )
        assert auth.access_token == "injected"

    @pytest.mark.asyncio
    async def test_token_refresher_seam(self, monkeypatch):
        expired = StoredToken(
            access_token="old",
            expires_at=time.time() - 100,
            refresh_token="refresh-token",
            tenant_key="t1",
            user_id="u1",
        )
        refreshed = StoredToken(
            access_token="new",
            expires_at=time.time() + 3600,
            refresh_token="refresh-token",
            tenant_key="t1",
            user_id="u1",
        )

        async def fake_refresh(_cfg, _token):
            return refreshed

        # OIDC discovery is async HTTP — short-circuit it.
        async def identity(c):
            return c

        monkeypatch.setattr("orchid_cli.auth.middleware.discover_oidc_endpoints", identity)

        saved: list[tuple[str, StoredToken]] = []
        auth = await get_auth_context(
            "",
            oauth_config=_cfg(),
            token_loader=lambda _: expired,
            token_saver=lambda cid, t: saved.append((cid, t)),
            token_refresher=fake_refresh,
        )

        assert auth.access_token == "new"
        assert saved == [("app", refreshed)]

    @pytest.mark.asyncio
    async def test_token_saver_seam(self, monkeypatch):
        expired = StoredToken(
            access_token="old",
            expires_at=time.time() - 100,
            refresh_token="r",
            tenant_key="t1",
            user_id="u1",
        )
        refreshed = StoredToken(
            access_token="fresh",
            expires_at=time.time() + 3600,
            refresh_token="r",
            tenant_key="t1",
            user_id="u1",
        )

        async def fake_refresh(_cfg, _token):
            return refreshed

        async def identity(c):
            return c

        monkeypatch.setattr("orchid_cli.auth.middleware.discover_oidc_endpoints", identity)

        captured: list[tuple[str, StoredToken]] = []

        await get_auth_context(
            "",
            oauth_config=_cfg(),
            token_loader=lambda _: expired,
            token_refresher=fake_refresh,
            token_saver=lambda cid, tok: captured.append((cid, tok)),
        )

        assert len(captured) == 1
        assert captured[0][0] == "app"
        assert captured[0][1].access_token == "fresh"
