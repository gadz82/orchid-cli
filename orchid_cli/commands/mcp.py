"""
MCP server management commands — authorize, status, revoke.

Handles per-server OAuth for MCP servers that declare ``auth.mode: oauth``
in their agents.yaml configuration.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import typer
from rich.console import Console
from rich.table import Table

from orchid_ai.config.loader import load_config
from orchid_ai.core.mcp import MCPTokenRecord
from orchid_ai.mcp.auth_registry import MCPAuthRegistry
from orchid_ai.persistence.mcp_token_factory import build_mcp_token_store

from ..auth.middleware import get_auth_context
from ..bootstrap import DEFAULT_STORAGE_DSN, DEFAULT_TOKEN_STORE_CLASS

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="mcp",
    help="MCP server management — authorize OAuth, check status, revoke tokens.",
    no_args_is_help=True,
)

console = Console()


# ── PKCE helpers ────────────────────────────────────────────────


def _generate_code_verifier(length: int = 64) -> str:
    return secrets.token_urlsafe(length)[:128]


def _generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _find_free_port(start: int = 9876, attempts: int = 20) -> int:
    import socket

    for port in range(start, start + attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Config helpers ──────────────────────────────────────────────


def _load_registry(config_path: str) -> MCPAuthRegistry:
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
    return MCPAuthRegistry.from_config(agents_config)


async def _discover_oidc_endpoints(issuer: str) -> dict[str, str]:
    """Fetch OIDC discovery document — delegates to shared utility."""
    from ..auth.oidc import discover_oidc_endpoints

    return await discover_oidc_endpoints(issuer)


async def _resolve_endpoints(
    server_info: Any,
) -> tuple[str, str]:
    """Resolve authorization and token endpoints (explicit or OIDC discovery).

    Returns (auth_endpoint, token_endpoint).  Either may be empty on failure.
    """
    auth_endpoint = server_info.authorization_endpoint
    token_endpoint = server_info.token_endpoint
    if not auth_endpoint and server_info.issuer:
        endpoints = await _discover_oidc_endpoints(server_info.issuer)
        auth_endpoint = endpoints.get("authorization_endpoint", "")
        token_endpoint = endpoints.get("token_endpoint", token_endpoint)
    return auth_endpoint, token_endpoint


# ── Shared PKCE OAuth flow ──────────────────────────────────────


@dataclass
class PKCEFlowResult:
    """Result of a PKCE OAuth browser flow."""

    success: bool
    access_token: str = ""
    refresh_token: str = ""
    expires_in: int = 3600
    error: str = ""


async def _run_pkce_flow(
    *,
    auth_endpoint: str,
    token_endpoint: str,
    client_id: str,
    scopes: str,
    timeout: float = 120.0,
) -> PKCEFlowResult:
    """Run the full PKCE OAuth flow: browser -> localhost callback -> token exchange.

    Starts a temporary localhost HTTP server, opens the browser for the
    IdP authorization page, waits for the redirect callback, and exchanges
    the authorization code for tokens.

    This is the single implementation shared by both ``_auto_authorize_servers``
    (called automatically by chat commands) and ``_authorize`` (explicit CLI command).
    """
    code_verifier = _generate_code_verifier()
    code_challenge = _generate_code_challenge(code_verifier)
    state = secrets.token_urlsafe(32)

    port = _find_free_port()
    redirect_uri = f"http://localhost:{port}/callback"

    received: dict[str, str] = {}

    class _CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            received["code"] = params.get("code", [""])[0]
            received["state"] = params.get("state", [""])[0]
            received["error"] = params.get("error", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authorization complete</h2><p>You can close this window.</p></body></html>"
            )

        def log_message(self, format, *args):
            pass  # suppress access logs

    http_server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    thread = Thread(target=http_server.handle_request, daemon=True)
    thread.start()

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    authorize_url = f"{auth_endpoint}?{urlencode(params)}"
    webbrowser.open(authorize_url)

    thread.join(timeout=timeout)
    http_server.server_close()

    # Validate callback
    if not received.get("code"):
        return PKCEFlowResult(success=False, error=received.get("error", "No response (timeout?)"))
    if received.get("state") != state:
        return PKCEFlowResult(success=False, error="State mismatch — possible CSRF")

    # Exchange code for tokens
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": received["code"],
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "code_verifier": code_verifier,
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return PKCEFlowResult(success=False, error=f"Token exchange failed (HTTP {exc.response.status_code})")
    except Exception as exc:
        return PKCEFlowResult(success=False, error=f"Token exchange failed: {exc}")

    return PKCEFlowResult(
        success=True,
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", ""),
        expires_in=data.get("expires_in", 3600),
    )


def _build_token_record(
    server_name: str,
    auth: Any,
    scopes: str,
    flow_result: PKCEFlowResult,
) -> MCPTokenRecord:
    """Build an ``MCPTokenRecord`` from a successful PKCE flow result."""
    now = time.time()
    return MCPTokenRecord(
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


# ── Auto-authorize (called by chat commands) ──────────────────


async def _auto_authorize_servers(
    server_names: list[str],
    registry: MCPAuthRegistry,
    auth: Any,
    store: Any,
    *,
    timeout: float = 120.0,
) -> list[str]:
    """Automatically trigger OAuth browser flow for unauthorized MCP servers.

    Called by chat commands before sending a message.  For each server,
    opens the browser for the PKCE flow.  Returns list of server names
    that were successfully authorized.
    """
    authorized: list[str] = []

    for server_name in server_names:
        server_info = registry.get_server(server_name)
        if not server_info:
            continue

        try:
            auth_endpoint, token_endpoint = await _resolve_endpoints(server_info)
        except Exception as exc:
            console.print(f"[yellow]Could not discover endpoints for '{server_name}': {exc}[/yellow]")
            continue

        if not auth_endpoint or not token_endpoint:
            console.print(f"[yellow]No endpoints for '{server_name}' — skipping.[/yellow]")
            continue

        console.print(f"\n[bold]MCP server '{server_name}' requires authorization.[/bold]")
        console.print("[dim]Opening browser...[/dim]")

        result = await _run_pkce_flow(
            auth_endpoint=auth_endpoint,
            token_endpoint=token_endpoint,
            client_id=server_info.client_id,
            scopes=server_info.scopes,
            timeout=timeout,
        )

        if not result.success:
            console.print(f"[yellow]Authorization failed for '{server_name}': {result.error}[/yellow]")
            continue

        record = _build_token_record(server_name, auth, server_info.scopes, result)
        await store.save_token(record)
        console.print(f"[green]Authorized '{server_name}'.[/green]")
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

    # Resolve endpoints
    try:
        auth_endpoint, token_endpoint = await _resolve_endpoints(server_info)
    except Exception as exc:
        console.print(f"[red]Could not discover endpoints: {exc}[/red]")
        raise typer.Exit(1) from exc

    if not auth_endpoint or not token_endpoint:
        console.print("[red]Cannot resolve authorization or token endpoint.[/red]")
        raise typer.Exit(1)

    auth = await get_auth_context(config_path)

    console.print(f"\n[bold]Authorizing MCP server:[/bold] {server_name}")
    console.print("[dim]Opening browser...[/dim]\n")

    result = await _run_pkce_flow(
        auth_endpoint=auth_endpoint,
        token_endpoint=token_endpoint,
        client_id=server_info.client_id,
        scopes=server_info.scopes,
        timeout=timeout,
    )

    if not result.success:
        console.print(f"[red]Authorization failed:[/red] {result.error}")
        raise typer.Exit(1)

    record = _build_token_record(server_name, auth, server_info.scopes, result)
    store = build_mcp_token_store(class_path=DEFAULT_TOKEN_STORE_CLASS, dsn=DEFAULT_STORAGE_DSN)
    await store.init_db()
    await store.save_token(record)
    await store.close()

    console.print(f"[green]Successfully authorized '{server_name}'.[/green]")


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
