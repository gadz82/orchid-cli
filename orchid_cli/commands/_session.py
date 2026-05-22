"""Shared CLI session helper — bootstrap + auth + MCP warm-up.

Every command that today ran ``bootstrap()`` and ``get_auth_context()``
side-by-side now goes through :func:`resolve_session` so the
per-user MCP capability cache is populated before the agent loop
starts.  The warmer's idempotency check makes a second call inside an
interactive REPL a near-instant no-op.

Failures in either layer are reported but never abort the command:
bootstrap exceptions surface to the caller (something is genuinely
broken); per-user warm exceptions are logged and ignored — the user's
chat still works, it just pays the lazy discovery cost on first use.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from orchid_ai import Orchid
from orchid_ai.core.state import OrchidAuthContext

from ..auth.middleware import get_auth_context
from ..bootstrap import bootstrap

logger = logging.getLogger(__name__)


async def resolve_session(
    config_path: str,
    *,
    model: str = "",
    content_paths: list[str] | None = None,
) -> tuple[Orchid, OrchidAuthContext]:
    """Bootstrap Orchid + resolve auth + warm passthrough/oauth caches.

    Returns the fully-started :class:`Orchid` facade and the resolved
    :class:`OrchidAuthContext`.  The caller owns the returned
    ``Orchid`` and must :meth:`Orchid.close` (or use
    :func:`session_context`) when done.

    Single helper used by every command that needs both an Orchid
    facade and a per-user auth context — keeps the warm-on-session-
    start lifecycle concentrated in one place (DRY + DIP, identical
    rule to ``orchid-api/auth.py``'s lazy backstop).
    """
    orchid = await bootstrap(config_path, model=model, content_paths=content_paths)
    auth = await get_auth_context(config_path)
    try:
        report = await orchid.session_warmer.warm_for_user(auth)
        if report.warmed or report.skipped or report.failed:
            logger.info(
                "[CLI] Per-user MCP warm-up: warmed=%s, skipped=%s, failed=%s",
                report.warmed,
                report.skipped,
                report.failed,
            )
    except Exception as exc:
        logger.warning("[CLI] Per-user MCP warm-up raised: %s", exc)
    return orchid, auth


@asynccontextmanager
async def session_context(config_path: str, *, model: str = "", content_paths: list[str] | None = None):
    """Async context manager wrapping :func:`resolve_session`.

    Mirrors :func:`orchid_cli.bootstrap.cli_context` but yields both
    the ``Orchid`` and the resolved ``OrchidAuthContext``.  Closing
    ``orchid`` is guaranteed even if the wrapped block raises.
    """
    orchid, auth = await resolve_session(config_path, model=model, content_paths=content_paths)
    try:
        yield orchid, auth
    finally:
        await orchid.close()
