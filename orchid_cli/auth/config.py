"""
OAuth provider configuration — parsed from the ``auth.cli`` section of orchid.yml.

Supports two modes:
  1. **OIDC discovery** — set ``issuer`` and endpoints are auto-discovered
     via ``{issuer}/.well-known/openid-configuration``.
  2. **Explicit endpoints** — set ``authorization_endpoint`` and
     ``token_endpoint`` directly.

When ``auth.dev_bypass: true`` or ``auth.cli`` is absent, the CLI falls
back to the legacy hardcoded dummy token (no OAuth).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OAuthProviderConfig:
    """Resolved OAuth provider settings — ready to use."""

    client_id: str
    authorization_endpoint: str
    token_endpoint: str
    scopes: str = "openid"
    # Optional OIDC issuer (informational after discovery).
    issuer: str = ""
    # Optional identity resolver class (for enriching AuthContext).
    identity_resolver_class: str = ""
    # Optional domain (passed to IdentityResolver.resolve).
    domain: str = ""


def load_oauth_config(config_path: str) -> OAuthProviderConfig | None:
    """Load OAuth config from the ``auth.cli`` section of orchid.yml.

    Returns ``None`` when:
      - ``auth.dev_bypass`` is truthy, OR
      - ``auth.cli`` section is absent or incomplete.
    """
    if not config_path:
        return None

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("[CLI Auth] Config file %s not found", config_path)
        return None

    auth_section = data.get("auth", {})
    if not isinstance(auth_section, dict):
        return None

    # dev_bypass means no OAuth
    if _is_truthy(auth_section.get("dev_bypass", False)):
        return None

    cli_section = auth_section.get("cli", {})
    if not isinstance(cli_section, dict) or not cli_section:
        return None

    client_id = cli_section.get("client_id", "")
    if not client_id:
        logger.warning("[CLI Auth] auth.cli.client_id is required for OAuth")
        return None

    scopes = cli_section.get("scopes", "openid")
    issuer = cli_section.get("issuer", "")
    auth_endpoint = cli_section.get("authorization_endpoint", "")
    token_endpoint = cli_section.get("token_endpoint", "")

    # Carry forward top-level auth fields for identity resolution.
    identity_resolver_class = auth_section.get("identity_resolver_class", "")
    domain = auth_section.get("domain", "")

    return OAuthProviderConfig(
        client_id=client_id,
        authorization_endpoint=auth_endpoint,
        token_endpoint=token_endpoint,
        scopes=scopes,
        issuer=issuer,
        identity_resolver_class=identity_resolver_class,
        domain=domain,
    )


async def discover_oidc_endpoints(config: OAuthProviderConfig) -> OAuthProviderConfig:
    """Resolve endpoints via OIDC discovery if ``issuer`` is set but endpoints are missing.

    Fetches ``{issuer}/.well-known/openid-configuration`` and extracts
    ``authorization_endpoint`` and ``token_endpoint``.

    If both endpoints are already set, returns ``config`` unchanged.
    """
    if config.authorization_endpoint and config.token_endpoint:
        return config

    if not config.issuer:
        raise ValueError(
            "OAuth config requires either 'issuer' (for OIDC discovery) "
            "or explicit 'authorization_endpoint' + 'token_endpoint'."
        )

    discovery_url = f"{config.issuer.rstrip('/')}/.well-known/openid-configuration"
    logger.info("[CLI Auth] Discovering OIDC endpoints from %s", discovery_url)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(discovery_url)
        resp.raise_for_status()
        metadata = resp.json()

    auth_ep = config.authorization_endpoint or metadata.get("authorization_endpoint", "")
    token_ep = config.token_endpoint or metadata.get("token_endpoint", "")

    if not auth_ep or not token_ep:
        raise ValueError(
            f"OIDC discovery at {discovery_url} did not provide "
            f"authorization_endpoint ({auth_ep!r}) or token_endpoint ({token_ep!r})."
        )

    logger.info("[CLI Auth] Discovered: authorization=%s, token=%s", auth_ep, token_ep)

    return OAuthProviderConfig(
        client_id=config.client_id,
        authorization_endpoint=auth_ep,
        token_endpoint=token_ep,
        scopes=config.scopes,
        issuer=config.issuer,
        identity_resolver_class=config.identity_resolver_class,
        domain=config.domain,
    )


def _is_truthy(value: object) -> bool:
    """Interpret YAML booleans and strings as truthy."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)
