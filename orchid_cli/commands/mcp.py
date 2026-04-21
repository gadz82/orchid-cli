"""
MCP server management commands — authorize, status, revoke.

Handles per-server OAuth for MCP servers that declare ``auth.mode: oauth``
in their agents.yaml configuration.  Low-level PKCE primitives live in
:mod:`orchid_cli.auth.pkce`; this module owns the CLI surface and the
MCP-specific policy (registry lookups, token record assembly, auto-auth
from chat commands).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from orchid_ai.config.loader import load_config
from orchid_ai.core.mcp import OrchidMCPTokenRecord
from orchid_ai.mcp.auth_registry import OrchidMCPAuthRegistry
from orchid_ai.persistence.mcp_token_factory import build_mcp_token_store

from ..auth.middleware import get_auth_context
from ..auth.pkce import BrowserOpener, PKCEFlowResult, run_pkce_flow
from ..bootstrap import DEFAULT_STORAGE_DSN, DEFAULT_TOKEN_STORE_CLASS

# Re-export the callable alias so existing callers keep working.
__all__ = ["BrowserOpener", "app"]

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="mcp",
    help="MCP server management — authorize OAuth, check status, revoke tokens.",
    no_args_is_help=True,
)

console = Console()


# ── Config helpers ──────────────────────────────────────────────


def _load_registry(config_path: str) -> OrchidMCPAuthRegistry:
    """Load agents config and build the auth registry."""
    import yaml

    agents_config_path = "agents.yaml"
    if config_path:
        try:
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            agents_config_path = data.get("agents", {}).get("config_path", agents_config_path)
        except FileNotFoundError:
            pass

    agents_config = load_config(agents_config_path)
    return OrchidMCPAuthRegistry.from_config(agents_config)


async def _discover_oidc_endpoints(issuer: str) -> dict[str, str]:
    """Fetch OIDC discovery document — delegates to shared utility."""
    from ..auth.oidc import discover_oidc_endpoints

    return await discover_oidc_endpoints(issuer)


async def _resolve_endpoints(server_info: Any) -> tuple[str, str]:
    """Resolve authorization and token endpoints (explicit or OIDC discovery).

    Returns ``(auth_endpoint, token_endpoint)`` — either may be empty on
    failure.
    """
    auth_endpoint = server_info.authorization_endpoint
    token_endpoint = server_info.token_endpoint
    if not auth_endpoint and server_info.issuer:
        endpoints = await _discover_oidc_endpoints(server_info.issuer)
        auth_endpoint = endpoints.get("authorization_endpoint", "")
        token_endpoint = endpoints.get("token_endpoint", token_endpoint)
    return auth_endpoint, token_endpoint


def _build_token_record(
    server_name: str,
    auth: Any,
    scopes: str,
    flow_result: PKCEFlowResult,
) -> OrchidMCPTokenRecord:
    """Build an ``OrchidMCPTokenRecord`` from a successful PKCE flow result."""
    now = time.time()
    return OrchidMCPTokenRecord(
        server_name=server_name,
        tenant_id=auth.tenant_key,
        user_id=auth.user_id,
        access_token=flow_result.access_token,
        refresh_token=flow_result.refresh_token,
        expires_at=now + flow_result.expires_in,
        scopes=scopes,
        created_at=now,
        updated_at=now,
    )


# ── Shared MCP authorization flow ──────────────────────────────


async def _perform_mcp_oauth_flow(
    server_name: str,
    server_info: Any,
    auth: Any,
    store: Any,
    *,
    timeout: float,
    severity: str = "yellow",
) -> bool:
    """Resolve endpoints, run PKCE, persist the resulting token record.

    Used by both the explicit ``orchid mcp authorize`` command and the
    ``_auto_authorize_servers`` flow invoked by chat commands.  Returns
    ``True`` on success, ``False`` on any recoverable failure; the
    explicit command raises :class:`typer.Exit(1)` on ``False`` while
    the auto-flow simply skips the server.

    Parameters
    ----------
    severity
        Rich colour used for warnings (endpoint-discovery failure,
        missing endpoints, PKCE error).  ``"yellow"`` for the auto-flow
        (advisory — keep the CLI going), ``"red"`` for the explicit
        command (terminal — user asked for this server).
    """
    try:
        auth_endpoint, token_endpoint = await _resolve_endpoints(server_info)
    except Exception as exc:
        console.print(f"[{severity}]Could not discover endpoints for '{server_name}': {exc}[/{severity}]")
        return False

    if not auth_endpoint or not token_endpoint:
        console.print(f"[{severity}]No endpoints for '{server_name}' — skipping.[/{severity}]")
        return False

    console.print(f"\n[bold]MCP server '{server_name}' requires authorization.[/bold]")
    console.print("[dim]Opening browser...[/dim]\n")

    result = await run_pkce_flow(
        auth_endpoint=auth_endpoint,
        token_endpoint=token_endpoint,
        client_id=server_info.client_id,
        scopes=server_info.scopes,
        timeout=timeout,
    )

    if not result.success:
        console.print(f"[{severity}]Authorization failed for '{server_name}': {result.error}[/{severity}]")
        return False

    record = _build_token_record(server_name, auth, server_info.scopes, result)
    await store.save_token(record)
    console.print(f"[green]Authorized '{server_name}'.[/green]")
    return True


async def _auto_authorize_servers(
    server_names: list[str],
    registry: OrchidMCPAuthRegistry,
    auth: Any,
    store: Any,
    *,
    timeout: float = 120.0,
) -> list[str]:
    """Automatically trigger OAuth browser flow for unauthorized MCP servers.

    Called by chat commands before sending a message.  For each server,
    opens the browser for the PKCE flow via :func:`_perform_mcp_oauth_flow`.
    Returns the list of server names that were successfully authorized.
    """
    authorized: list[str] = []
    for server_name in server_names:
        server_info = registry.get_server(server_name)
        if server_info is None:
            continue
        if await _perform_mcp_oauth_flow(server_name, server_info, auth, store, timeout=timeout):
            authorized.append(server_name)
    return authorized


# ── Commands ─────────────────────────────────────────────────


@app.command("status")
def status_cmd(
    config: str = typer.Option("", "-c", "--config", help="Path to orchid.yml"),
):
    """Show OAuth authorization status for all MCP servers."""
    asyncio.run(_status(config))


async def _status(config_path: str) -> None:
    registry = _load_registry(config_path)

    if registry.empty:
        console.print("[dim]No MCP servers require OAuth authorization.[/dim]")
        return

    auth = await get_auth_context(config_path)
    store = build_mcp_token_store(class_path=DEFAULT_TOKEN_STORE_CLASS, dsn=DEFAULT_STORAGE_DSN)
    await store.init_db()

    table = Table(title="MCP OAuth Servers")
    table.add_column("Server", style="bold")
    table.add_column("Status")
    table.add_column("Agents")
    table.add_column("Scopes", style="dim")

    for name, info in registry.oauth_servers.items():
        token = await store.get_token(auth.tenant_key, auth.user_id, name)
        if token and not token.is_expired:
            status = "[green]Authorized[/green]"
        elif token and token.is_expired:
            status = "[yellow]Expired[/yellow]"
        else:
            status = "[red]Not authorized[/red]"

        table.add_row(
            name,
            status,
            ", ".join(info.agent_names),
            info.scopes,
        )

    console.print(table)
    await store.close()


@app.command("authorize")
def authorize_cmd(
    server_name: str = typer.Argument(help="Name of the MCP server to authorize"),
    config: str = typer.Option("", "-c", "--config", help="Path to orchid.yml"),
    timeout: float = typer.Option(120.0, help="Timeout in seconds for the browser flow"),
):
    """Authorize an OAuth MCP server via browser login (PKCE flow)."""
    asyncio.run(_authorize(server_name, config, timeout))


async def _authorize(server_name: str, config_path: str, timeout: float) -> None:
    registry = _load_registry(config_path)
    server_info = registry.get_server(server_name)

    if not server_info:
        available = list(registry.oauth_servers.keys())
        if available:
            console.print(f"[red]Server '{server_name}' not found.[/red] Available: {', '.join(available)}")
        else:
            console.print("[red]No MCP servers require OAuth authorization.[/red]")
        raise typer.Exit(1)

    auth = await get_auth_context(config_path)
    store = build_mcp_token_store(class_path=DEFAULT_TOKEN_STORE_CLASS, dsn=DEFAULT_STORAGE_DSN)
    await store.init_db()
    try:
        ok = await _perform_mcp_oauth_flow(
            server_name,
            server_info,
            auth,
            store,
            timeout=timeout,
            severity="red",  # explicit command — failures are terminal
        )
    finally:
        await store.close()

    if not ok:
        raise typer.Exit(1)


@app.command("revoke")
def revoke_cmd(
    server_name: str = typer.Argument(help="Name of the MCP server to revoke authorization for"),
    config: str = typer.Option("", "-c", "--config", help="Path to orchid.yml"),
):
    """Revoke stored OAuth token for an MCP server."""
    asyncio.run(_revoke(server_name, config))


async def _revoke(server_name: str, config_path: str) -> None:
    auth = await get_auth_context(config_path)
    store = build_mcp_token_store(class_path=DEFAULT_TOKEN_STORE_CLASS, dsn=DEFAULT_STORAGE_DSN)
    await store.init_db()

    deleted = await store.delete_token(auth.tenant_key, auth.user_id, server_name)
    await store.close()

    if deleted:
        console.print(f"[green]Token revoked for '{server_name}'.[/green]")
    else:
        console.print(f"[yellow]No token found for '{server_name}'.[/yellow]")
