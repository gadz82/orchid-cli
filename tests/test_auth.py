"""Tests for orchid-cli OAuth authentication module."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchid_cli.auth.config import OAuthProviderConfig, discover_oidc_endpoints, load_oauth_config
from orchid_cli.auth.flow import (
    _generate_code_challenge,
    _generate_code_verifier,
)
from orchid_cli.auth.middleware import _DEV_AUTH, get_auth_context
from orchid_cli.auth.token_store import StoredToken, delete_token, load_token, save_token


# ── Config Tests ──────────────────────────────────────────────


class TestLoadOAuthConfig:
    def test_returns_none_when_no_config_path(self):
        assert load_oauth_config("") is None

    def test_returns_none_when_file_not_found(self, tmp_path):
        assert load_oauth_config(str(tmp_path / "nonexistent.yml")) is None

    def test_returns_none_when_dev_bypass_true(self, tmp_path):
        cfg_file = tmp_path / "orchid.yml"
        cfg_file.write_text(
            "auth:\n"
            "  dev_bypass: true\n"
            "  cli:\n"
            "    client_id: test\n"
            "    issuer: https://example.com\n"
        )
        assert load_oauth_config(str(cfg_file)) is None

    def test_returns_none_when_no_cli_section(self, tmp_path):
        cfg_file = tmp_path / "orchid.yml"
        cfg_file.write_text("auth:\n  dev_bypass: false\n")
        assert load_oauth_config(str(cfg_file)) is None

    def test_returns_none_when_no_client_id(self, tmp_path):
        cfg_file = tmp_path / "orchid.yml"
        cfg_file.write_text(
            "auth:\n"
            "  dev_bypass: false\n"
            "  cli:\n"
            "    scopes: openid\n"
        )
        assert load_oauth_config(str(cfg_file)) is None

    def test_returns_config_with_explicit_endpoints(self, tmp_path):
        cfg_file = tmp_path / "orchid.yml"
        cfg_file.write_text(
            "auth:\n"
            "  dev_bypass: false\n"
            "  identity_resolver_class: myapp.identity.Resolver\n"
            "  domain: example.com\n"
            "  cli:\n"
            "    client_id: my-app\n"
            "    scopes: openid api\n"
            "    authorization_endpoint: https://example.com/oauth2/authorize\n"
            "    token_endpoint: https://example.com/oauth2/token\n"
        )
        cfg = load_oauth_config(str(cfg_file))
        assert cfg is not None
        assert cfg.client_id == "my-app"
        assert cfg.scopes == "openid api"
        assert cfg.authorization_endpoint == "https://example.com/oauth2/authorize"
        assert cfg.token_endpoint == "https://example.com/oauth2/token"
        assert cfg.identity_resolver_class == "myapp.identity.Resolver"
        assert cfg.domain == "example.com"

    def test_returns_config_with_oidc_issuer(self, tmp_path):
        cfg_file = tmp_path / "orchid.yml"
        cfg_file.write_text(
            "auth:\n"
            "  dev_bypass: false\n"
            "  cli:\n"
            "    client_id: my-app\n"
            "    issuer: https://auth.example.com\n"
        )
        cfg = load_oauth_config(str(cfg_file))
        assert cfg is not None
        assert cfg.client_id == "my-app"
        assert cfg.issuer == "https://auth.example.com"
        assert cfg.authorization_endpoint == ""
        assert cfg.token_endpoint == ""

    def test_dev_bypass_string_true(self, tmp_path):
        cfg_file = tmp_path / "orchid.yml"
        cfg_file.write_text(
            "auth:\n"
            "  dev_bypass: 'true'\n"
            "  cli:\n"
            "    client_id: test\n"
        )
        assert load_oauth_config(str(cfg_file)) is None


class TestDiscoverOIDCEndpoints:
    @pytest.mark.asyncio
    async def test_returns_unchanged_when_endpoints_present(self):
        cfg = OAuthProviderConfig(
            client_id="app",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
        )
        result = await discover_oidc_endpoints(cfg)
        assert result is cfg

    @pytest.mark.asyncio
    async def test_raises_when_no_issuer_and_no_endpoints(self):
        cfg = OAuthProviderConfig(client_id="app", authorization_endpoint="", token_endpoint="")
        with pytest.raises(ValueError, match="requires either 'issuer'"):
            await discover_oidc_endpoints(cfg)

    @pytest.mark.asyncio
    async def test_fetches_discovery_document(self):
        cfg = OAuthProviderConfig(
            client_id="app",
            authorization_endpoint="",
            token_endpoint="",
            issuer="https://auth.example.com",
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "authorization_endpoint": "https://auth.example.com/oauth2/authorize",
            "token_endpoint": "https://auth.example.com/oauth2/token",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("orchid_cli.auth.config.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await discover_oidc_endpoints(cfg)

        assert result.authorization_endpoint == "https://auth.example.com/oauth2/authorize"
        assert result.token_endpoint == "https://auth.example.com/oauth2/token"
        assert result.client_id == "app"
        assert result.issuer == "https://auth.example.com"


# ── PKCE Tests ────────────────────────────────────────────────


class TestPKCE:
    def test_code_verifier_length(self):
        verifier = _generate_code_verifier()
        assert 43 <= len(verifier) <= 128

    def test_code_verifier_is_random(self):
        v1 = _generate_code_verifier()
        v2 = _generate_code_verifier()
        assert v1 != v2

    def test_code_challenge_is_deterministic(self):
        verifier = "test-verifier-12345678901234567890123456789012"
        c1 = _generate_code_challenge(verifier)
        c2 = _generate_code_challenge(verifier)
        assert c1 == c2

    def test_code_challenge_is_base64url(self):
        verifier = _generate_code_verifier()
        challenge = _generate_code_challenge(verifier)
        # Base64url: only alphanumeric, -, _
        assert all(c.isalnum() or c in "-_" for c in challenge)
        # No padding
        assert "=" not in challenge


# ── Token Store Tests ─────────────────────────────────────────


class TestTokenStore:
    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr("orchid_cli.auth.token_store._TOKEN_FILE", tmp_path / "tokens.json")
        monkeypatch.setattr("orchid_cli.auth.token_store._ORCHID_DIR", tmp_path)

        token = StoredToken(
            access_token="abc123",
            refresh_token="refresh456",
            expires_at=time.time() + 3600,
            tenant_key="t1",
            user_id="u1",
        )
        save_token("my-app", token)
        loaded = load_token("my-app")

        assert loaded is not None
        assert loaded.access_token == "abc123"
        assert loaded.refresh_token == "refresh456"
        assert loaded.tenant_key == "t1"
        assert loaded.user_id == "u1"

    def test_load_nonexistent_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("orchid_cli.auth.token_store._TOKEN_FILE", tmp_path / "tokens.json")
        assert load_token("nonexistent") is None

    def test_delete_token(self, tmp_path, monkeypatch):
        monkeypatch.setattr("orchid_cli.auth.token_store._TOKEN_FILE", tmp_path / "tokens.json")
        monkeypatch.setattr("orchid_cli.auth.token_store._ORCHID_DIR", tmp_path)

        save_token("my-app", StoredToken(access_token="abc"))
        assert delete_token("my-app") is True
        assert load_token("my-app") is None

    def test_delete_nonexistent_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr("orchid_cli.auth.token_store._TOKEN_FILE", tmp_path / "tokens.json")
        assert delete_token("nope") is False

    def test_multiple_clients(self, tmp_path, monkeypatch):
        monkeypatch.setattr("orchid_cli.auth.token_store._TOKEN_FILE", tmp_path / "tokens.json")
        monkeypatch.setattr("orchid_cli.auth.token_store._ORCHID_DIR", tmp_path)

        save_token("app-a", StoredToken(access_token="token-a"))
        save_token("app-b", StoredToken(access_token="token-b"))

        a = load_token("app-a")
        b = load_token("app-b")
        assert a is not None and a.access_token == "token-a"
        assert b is not None and b.access_token == "token-b"

    def test_stored_token_is_expired(self):
        expired = StoredToken(access_token="x", expires_at=time.time() - 100)
        assert expired.is_expired is True

        fresh = StoredToken(access_token="x", expires_at=time.time() + 3600)
        assert fresh.is_expired is False

        no_expiry = StoredToken(access_token="x", expires_at=0)
        assert no_expiry.is_expired is False


# ── Middleware Tests ──────────────────────────────────────────


class TestGetAuthContext:
    @pytest.mark.asyncio
    async def test_returns_dev_auth_when_no_oauth_config(self, tmp_path):
        cfg_file = tmp_path / "orchid.yml"
        cfg_file.write_text("auth:\n  dev_bypass: true\n")
        auth = await get_auth_context(str(cfg_file))
        assert auth.access_token == "cli-token"
        assert auth.tenant_key == "cli"

    @pytest.mark.asyncio
    async def test_returns_dev_auth_when_no_stored_token(self, tmp_path, monkeypatch):
        monkeypatch.setattr("orchid_cli.auth.middleware.load_token", lambda _: None)

        cfg = OAuthProviderConfig(
            client_id="app",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
        )
        auth = await get_auth_context("", oauth_config=cfg)
        assert auth == _DEV_AUTH

    @pytest.mark.asyncio
    async def test_returns_auth_from_stored_token(self, monkeypatch):
        token = StoredToken(
            access_token="real-token",
            expires_at=time.time() + 3600,
            tenant_key="tenant-42",
            user_id="user-abc",
        )
        monkeypatch.setattr("orchid_cli.auth.middleware.load_token", lambda _: token)

        cfg = OAuthProviderConfig(
            client_id="app",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
        )
        auth = await get_auth_context("", oauth_config=cfg)
        assert auth.access_token == "real-token"
        assert auth.tenant_key == "tenant-42"
        assert auth.user_id == "user-abc"

    @pytest.mark.asyncio
    async def test_returns_dev_auth_when_token_expired_no_refresh(self, monkeypatch):
        token = StoredToken(
            access_token="expired",
            expires_at=time.time() - 100,
            refresh_token="",
        )
        monkeypatch.setattr("orchid_cli.auth.middleware.load_token", lambda _: token)

        cfg = OAuthProviderConfig(
            client_id="app",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
        )
        auth = await get_auth_context("", oauth_config=cfg)
        assert auth == _DEV_AUTH

    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self, monkeypatch):
        expired_token = StoredToken(
            access_token="old",
            expires_at=time.time() - 100,
            refresh_token="refresh-xyz",
            tenant_key="t1",
            user_id="u1",
        )
        monkeypatch.setattr("orchid_cli.auth.middleware.load_token", lambda _: expired_token)
        monkeypatch.setattr("orchid_cli.auth.middleware.discover_oidc_endpoints", AsyncMock(side_effect=lambda c: c))

        refreshed = StoredToken(
            access_token="new-token",
            expires_at=time.time() + 3600,
            refresh_token="refresh-xyz",
            tenant_key="t1",
            user_id="u1",
        )

        async def mock_refresh(config, token):
            return refreshed

        monkeypatch.setattr("orchid_cli.auth.middleware._refresh_token", mock_refresh)
        saved_tokens = []
        monkeypatch.setattr("orchid_cli.auth.middleware.save_token", lambda cid, t: saved_tokens.append((cid, t)))

        cfg = OAuthProviderConfig(
            client_id="app",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
        )
        auth = await get_auth_context("", oauth_config=cfg)
        assert auth.access_token == "new-token"
        assert len(saved_tokens) == 1


# ── StoredToken property tests ────────────────────────────────


class TestStoredTokenProperties:
    def test_is_refresh_available(self):
        with_refresh = StoredToken(access_token="x", refresh_token="r")
        assert with_refresh.is_refresh_available is True

        without_refresh = StoredToken(access_token="x", refresh_token="")
        assert without_refresh.is_refresh_available is False
