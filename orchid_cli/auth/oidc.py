"""Shared OIDC discovery utility."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


async def discover_oidc_endpoints(issuer: str) -> dict[str, str]:
    """Fetch OIDC discovery document and return endpoint URLs.

    Returns a dict with ``authorization_endpoint`` and ``token_endpoint`` keys.
    Shared by ``commands/mcp.py`` and ``auth/config.py``.
    """
    well_known = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    logger.info("[OIDC] Discovering endpoints from %s", well_known)

    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.get(well_known)
        resp.raise_for_status()
        data = resp.json()

    return {
        "authorization_endpoint": data.get("authorization_endpoint", ""),
        "token_endpoint": data.get("token_endpoint", ""),
    }
