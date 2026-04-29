"""
MCP server management commands — status, revoke.

Reports per-server OAuth status and lets the user revoke stored
tokens.  The CLI does **not** drive the OAuth dance itself — that
happens through the API gateway via the chat path's per-user warm.
"""

from __future__ import annotations

import logging

import typer
from rich.console import Console
from rich.table import Table

from orchid_ai.config.loader import load_config
from orchid_ai.mcp.auth_registry import OrchidMCPAuthRegistry
from orchid_ai.persistence.mcp_token_factory import build_mcp_token_store

from .._typer_async import async_command
from ..auth.middleware import get_auth_context
from ..bootstrap import DEFAULT_STORAGE_DSN, DEFAULT_TOKEN_STORE_CLASS

logger = logging.getLogger(__name__)

app = typer.Typer(
    name="mcp",
    help="MCP server management — check OAuth status and revoke tokens.",
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


# ── Commands ─────────────────────────────────────────────────


@app.command("status")
@async_command
async def status_cmd(
    config: str = typer.Option("", "-c", "--config", help="Path to orchid.yml"),
) -> None:
    """Show OAuth authorization status for all MCP servers."""
    await _status(config)


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
        )

    console.print(table)
    await store.close()


@app.command("revoke")
@async_command
async def revoke_cmd(
    server_name: str = typer.Argument(help="Name of the MCP server to revoke authorization for"),
    config: str = typer.Option("", "-c", "--config", help="Path to orchid.yml"),
) -> None:
    """Revoke stored OAuth token for an MCP server."""
    await _revoke(server_name, config)


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
