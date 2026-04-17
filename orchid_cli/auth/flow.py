"""
OAuth 2.0 Authorization Code + PKCE flow for CLI user login.

The low-level primitives (PKCE derivations, localhost callback server,
token exchange, full orchestration) live in :mod:`.pkce`; this module
layers user-login policy on top and returns a :class:`StoredToken`
instead of the lower-level :class:`PKCEFlowResult`.
"""

from __future__ import annotations

import logging
import time

from .config import OAuthProviderConfig
from .pkce import BrowserOpener, run_pkce_flow
from .token_store import StoredToken

# Re-export ``BrowserOpener`` so existing callers keep working.
__all__ = ["BrowserOpener", "run_login_flow"]

logger = logging.getLogger(__name__)


async def run_login_flow(
    config: OAuthProviderConfig,
    *,
    timeout: float = 120,
    browser_opener: BrowserOpener | None = None,
) -> StoredToken:
    """Execute the full Authorization Code + PKCE flow.

    1. Generate PKCE verifier/challenge.
    2. Open the browser to the authorization URL.
    3. Wait for the callback on a localhost port.
    4. Exchange the code for tokens.

    Parameters
    ----------
    browser_opener
        Callable used to launch the browser.  Defaults to
        :func:`webbrowser.open`.  Override in tests or headless
        environments to redirect or suppress the browser launch.

    Raises
    ------
    RuntimeError
        When the flow fails (timeout, OAuth error, token exchange
        failure).  The message is safe to surface to the user.
    """
    kwargs: dict = {
        "auth_endpoint": config.authorization_endpoint,
        "token_endpoint": config.token_endpoint,
        "client_id": config.client_id,
        "scopes": config.scopes,
        "timeout": timeout,
        "success_title": "Authentication successful",
        "success_body": "You can close this browser tab and return to the terminal.",
    }
    if browser_opener is not None:
        kwargs["browser_opener"] = browser_opener

    logger.info("[CLI Auth] Opening browser for login: %s", config.authorization_endpoint)
    result = await run_pkce_flow(**kwargs)

    if not result.success:
        raise RuntimeError(f"OAuth login failed: {result.error}")

    expires_at = (time.time() + result.expires_in) if result.expires_in else 0.0
    return StoredToken(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_at=expires_at,
        scopes=result.scopes or config.scopes,
    )
