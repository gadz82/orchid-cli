"""
Auth middleware — resolves the current CLI session into an ``AuthContext``.

Responsibilities:
  1. Load stored token from disk.
  2. Refresh if expired (using the refresh_token grant).
  3. Build an ``AuthContext`` for graph injection.
  4. Optionally enrich via ``IdentityResolver`` (if configured).

When no OAuth is configured (``auth.dev_bypass: true`` or no ``auth.cli``
section), returns a fallback dummy context for local development.
"""

from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

import httpx

from orchid_ai.core.state import AuthContext

from .config import OAuthProviderConfig, discover_oidc_endpoints, load_oauth_config
from .token_store import StoredToken, load_token, save_token

logger = logging.getLogger(__name__)

# Fallback context for dev/local use (matches legacy behaviour).
_DEV_AUTH = AuthContext(
    access_token="cli-token",
    tenant_key="cli",
    user_id="cli-user",
)


# ── Injectable seams ─────────────────────────────────────────
#
# Default to the production dependencies; tests pass fakes that
# bypass disk I/O and HTTP without monkey-patching three modules.

TokenLoader = Callable[[str], "StoredToken | None"]
TokenSaver = Callable[[str, "StoredToken"], None]
TokenRefresher = Callable[[OAuthProviderConfig, StoredToken], Awaitable[StoredToken]]


async def get_auth_context(
    config_path: str,
    *,
    oauth_config: OAuthProviderConfig | None = None,
    token_loader: TokenLoader | None = None,
    token_saver: TokenSaver | None = None,
    token_refresher: TokenRefresher | None = None,
) -> AuthContext:
    """Build an ``AuthContext`` for the current CLI session.

    Resolution order:
      1. If OAuth is configured → load stored token, refresh if needed.
      2. If ``IdentityResolver`` is configured → enrich with tenant/user.
      3. Otherwise → return development fallback.

    Parameters
    ----------
    token_loader, token_saver
        Persistence seams.  Default to the on-disk ``~/.orchid/tokens.json``
        implementation.
    token_refresher
        Async callable exchanging a refresh token for a fresh access
        token.  Default calls the IdP's token endpoint via ``httpx``.
        Override in tests to avoid real HTTP.
    """
    # Resolve the seams lazily so module-level ``monkeypatch.setattr`` in
    # tests still works — binding ``load_token``/``save_token`` as default
    # argument values would freeze the reference at import time.
    loader = token_loader if token_loader is not None else load_token
    saver = token_saver if token_saver is not None else save_token
    refresher = token_refresher or _refresh_token

    cfg = oauth_config or load_oauth_config(config_path)
    if cfg is None:
        logger.debug("[CLI Auth] No OAuth configured — using dev auth context")
        return _DEV_AUTH

    token = loader(cfg.client_id)
    if token is None:
        logger.warning("[CLI Auth] No stored token. Run 'orchid auth login' first. Falling back to dev auth.")
        return _DEV_AUTH

    # Refresh if expired.
    if token.is_expired and token.is_refresh_available:
        try:
            cfg = await discover_oidc_endpoints(cfg)
            token = await refresher(cfg, token)
            saver(cfg.client_id, token)
            logger.info("[CLI Auth] Token refreshed successfully")
        except Exception as exc:
            logger.warning("[CLI Auth] Token refresh failed: %s. Run 'orchid auth login'.", exc)
            return _DEV_AUTH

    if token.is_expired:
        logger.warning("[CLI Auth] Token expired and no refresh token. Run 'orchid auth login'.")
        return _DEV_AUTH

    # Build AuthContext — use stored identity if available.
    auth = AuthContext(
        access_token=token.access_token,
        tenant_key=token.tenant_key or "default",
        user_id=token.user_id or "cli-user",
        expires_at=token.expires_at,
    )

    # Optionally resolve identity via IdentityResolver.
    if cfg.identity_resolver_class and (not token.tenant_key or not token.user_id):
        auth = await _resolve_identity(cfg, token, auth)

    return auth


async def _refresh_token(
    config: OAuthProviderConfig,
    token: StoredToken,
) -> StoredToken:
    """Use the refresh_token grant to obtain a new access token."""
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": token.refresh_token,
        "client_id": config.client_id,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            config.token_endpoint,
            data=payload,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

    expires_in = data.get("expires_in", 0)
    expires_at = (time.time() + expires_in) if expires_in else 0.0

    return StoredToken(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", token.refresh_token),
        expires_at=expires_at,
        scopes=data.get("scope", token.scopes),
        # Preserve identity from previous token.
        tenant_key=token.tenant_key,
        user_id=token.user_id,
        extra=token.extra,
    )


async def _resolve_identity(
    config: OAuthProviderConfig,
    token: StoredToken,
    auth: AuthContext,
) -> AuthContext:
    """Optionally enrich AuthContext via the configured IdentityResolver.

    This allows the CLI to populate ``tenant_key`` and ``user_id``
    from the OAuth token, just like orchid-api does at request time.
    """
    try:
        from orchid_ai.utils import import_class

        resolver_cls = import_class(config.identity_resolver_class)

        async with httpx.AsyncClient(timeout=15) as http_client:
            resolver = resolver_cls(http_client=http_client)
            resolved_auth = await resolver.resolve(config.domain, token.access_token)

        # Persist identity fields so future loads don't need the resolver.
        token.tenant_key = resolved_auth.tenant_key
        token.user_id = resolved_auth.user_id
        save_token(config.client_id, token)

        logger.info(
            "[CLI Auth] Identity resolved: tenant=%s, user=%s",
            resolved_auth.tenant_key,
            resolved_auth.user_id,
        )
        return resolved_auth

    except Exception as exc:
        logger.warning("[CLI Auth] Identity resolution failed: %s", exc)
        return auth
