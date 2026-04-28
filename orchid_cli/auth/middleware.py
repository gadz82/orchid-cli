"""
Auth middleware — resolves the current CLI session into an ``OrchidAuthContext``.

Responsibilities:
  1. Load stored token from disk.
  2. Refresh if expired (using the refresh_token grant).
  3. Build an ``OrchidAuthContext`` for graph injection.
  4. Optionally enrich via ``OrchidIdentityResolver`` (if configured).

When no OAuth is configured (``auth.dev_bypass: true`` or no ``auth.cli``
section), returns a fallback dummy context for local development.
"""

from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

import httpx

from orchid_ai.core.state import OrchidAuthContext

from .config import OAuthProviderConfig, discover_oidc_endpoints, load_oauth_config
from .token_store import StoredToken, load_token, save_token

logger = logging.getLogger(__name__)

# Fallback context for dev/local use (matches legacy behaviour).
_DEV_AUTH = OrchidAuthContext(
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
) -> OrchidAuthContext:
    """Build an ``OrchidAuthContext`` for the current CLI session.

    Resolution order:
      1. If OAuth is configured → load stored token, refresh if needed.
      2. If ``OrchidIdentityResolver`` is configured → enrich with tenant/user.
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

    # ── Fast path — rebuild the typed subclass from the cache ──
    #
    # When the most recent login resolved an identity, both
    # ``auth_class`` (FQN) and ``auth_state`` (the dict produced by
    # ``OrchidAuthContext.to_storage_dict()``) were persisted on the
    # token.  We rebuild the typed instance directly here — no
    # network round-trip — and pass the fresh ``access_token`` /
    # ``expires_at`` from the (possibly just-refreshed) token in
    # case they rolled over.
    if token.auth_class and token.auth_state:
        try:
            from orchid_ai.utils import import_class

            cls = import_class(token.auth_class)
            return cls.from_storage_dict(
                access_token=token.access_token,
                expires_at=token.expires_at,
                state=dict(token.auth_state),
            )
        except Exception as exc:
            # Cache restoration failed — most likely the resolver's
            # subclass moved or its ``from_storage_dict`` got a
            # breaking change.  Log loudly and fall through to the
            # resolver (slow path); the operator will see the
            # warning and can ``orchid auth login`` once to refresh
            # the cache shape.
            logger.warning(
                "[CLI Auth] Cached identity rebuild failed (%s: %s) — falling back to live resolver",
                type(exc).__name__,
                exc,
            )

    # ── Slow path — call the resolver, then cache for next time ──
    #
    # Used on first login (cache empty), after a manual ``orchid
    # auth logout``, OR when the cached subclass-class moved and we
    # had to bail out of the fast path above.
    auth = OrchidAuthContext(
        access_token=token.access_token,
        tenant_key=token.tenant_key or "default",
        user_id=token.user_id or "cli-user",
        expires_at=token.expires_at,
        extra=dict(token.extra) if token.extra else None,
    )
    if cfg.identity_resolver_class:
        auth = await _resolve_identity(cfg, token, auth)
        # Persist the freshly-resolved identity so the NEXT command
        # takes the fast path above.  Mirror the same logic as
        # ``commands/auth.py:_resolve_and_store_identity`` so a
        # one-off ``orchid chat`` against a token that lost its
        # cache (e.g. legacy tokens written before this feature
        # existed) self-heals on first use.
        if type(auth) is not OrchidAuthContext:
            token.auth_class = f"{type(auth).__module__}.{type(auth).__qualname__}"
            token.auth_state = auth.to_storage_dict()
            saver(cfg.client_id, token)

    return auth


async def _refresh_token(
    config: OAuthProviderConfig,
    token: StoredToken,
) -> StoredToken:
    """Use the refresh_token grant to obtain a new access token.

    Mirrors :func:`exchange_code_for_tokens` — when the OAuth server
    treats the CLI as a confidential client, the refresh grant ALSO
    needs ``client_secret`` in the form body.  Pure-public PKCE
    deployments leave ``config.client_secret`` empty and the field is
    omitted.
    """
    payload: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": token.refresh_token,
        "client_id": config.client_id,
    }
    if config.client_secret:
        payload["client_secret"] = config.client_secret

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
    auth: OrchidAuthContext,
) -> OrchidAuthContext:
    """Optionally enrich OrchidAuthContext via the configured OrchidIdentityResolver.

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
