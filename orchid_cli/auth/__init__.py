"""
OAuth authentication for orchid-cli.

Provides generic OAuth 2.0 Authorization Code + PKCE flow,
token storage, and automatic refresh. Works with any standard
OAuth 2.0 / OIDC provider.

Usage::

    from orchid_cli.auth.middleware import get_auth_context

    auth = await get_auth_context(config_path="orchid.yml")
"""

from __future__ import annotations
