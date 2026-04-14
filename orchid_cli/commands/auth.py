"""
Auth commands — OAuth login, logout, and status.

    orchid auth login  --config orchid.yml   # Opens browser for OAuth login
    orchid auth status --config orchid.yml   # Show current auth state
    orchid auth logout --config orchid.yml   # Clear stored tokens
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console

from ..auth.config import discover_oidc_endpoints, load_oauth_config
from ..auth.flow import run_login_flow
from ..auth.token_store import StoredToken, delete_token, load_token, save_token

app = typer.Typer(help="OAuth authentication management", no_args_is_help=True)
console = Console()


@app.command()
def login(
    config: str = typer.Option(..., "--config", "-c", help="Path to orchid.yml"),
    timeout: float = typer.Option(120, "--timeout", "-t", help="Timeout in seconds for browser login"),
):
    """Authenticate via OAuth (opens browser)."""
    asyncio.run(_login(config, timeout))


async def _login(config_path: str, timeout: float) -> None:
    cfg = load_oauth_config(config_path)
    if cfg is None:
        console.print(
            "[yellow]No OAuth configuration found.[/yellow]\n\n"
            "To enable OAuth, add an [bold]auth.cli[/bold] section to your orchid.yml:\n\n"
            "  auth:\n"
            "    dev_bypass: false\n"
            "    cli:\n"
            "      client_id: my-app\n"
            "      scopes: openid api\n"
            "      issuer: https://provider.example.com   # OIDC auto-discovery\n"
            "      # OR explicit endpoints:\n"
            "      # authorization_endpoint: https://provider.example.com/oauth2/authorize\n"
            "      # token_endpoint: https://provider.example.com/oauth2/token\n"
        )
        raise typer.Exit(1)

    # Discover OIDC endpoints if needed.
    try:
        cfg = await discover_oidc_endpoints(cfg)
    except (ValueError, Exception) as exc:
        console.print(f"[red]OIDC discovery failed:[/red] {exc}")
        raise typer.Exit(1) from None

    console.print("[bold]Opening browser for authentication...[/bold]")
    console.print(f"  Provider: {cfg.issuer or cfg.authorization_endpoint}")
    console.print(f"  Client ID: {cfg.client_id}")
    console.print(f"  Scopes: {cfg.scopes}")
    console.print()

    try:
        token = await run_login_flow(cfg, timeout=timeout)
    except RuntimeError as exc:
        console.print(f"[red]Login failed:[/red] {exc}")
        raise typer.Exit(1) from None

    # Optionally resolve identity.
    if cfg.identity_resolver_class:
        console.print("[dim]Resolving identity...[/dim]")
        try:
            await _resolve_and_store_identity(cfg, token)
        except Exception as exc:
            console.print(f"[yellow]Identity resolution failed:[/yellow] {exc}")
            console.print("[dim]Token saved without identity. MCP calls will use the Bearer token.[/dim]")

    save_token(cfg.client_id, token)

    console.print()
    console.print("[bold green]Logged in successfully.[/bold green]")
    _print_token_info(token)
    console.print("\n  Token stored at [dim]~/.orchid/tokens.json[/dim]")


@app.command()
def logout(
    config: str = typer.Option(..., "--config", "-c", help="Path to orchid.yml"),
):
    """Clear stored OAuth tokens."""
    cfg = load_oauth_config(config)
    if cfg is None:
        console.print("[yellow]No OAuth configuration found in orchid.yml.[/yellow]")
        raise typer.Exit(1)

    if delete_token(cfg.client_id):
        console.print("[bold]Logged out.[/bold] Token cleared.")
    else:
        console.print("[dim]No stored token found.[/dim]")


@app.command()
def status(
    config: str = typer.Option(..., "--config", "-c", help="Path to orchid.yml"),
):
    """Show current authentication status."""
    cfg = load_oauth_config(config)
    if cfg is None:
        console.print("[yellow]OAuth not configured.[/yellow] Using dev auth (cli-token).")
        return

    token = load_token(cfg.client_id)
    if token is None:
        console.print("[red]Not authenticated.[/red] Run [bold]orchid auth login -c <config>[/bold] to log in.")
        return

    if token.is_expired:
        if token.is_refresh_available:
            console.print("[yellow]Token expired[/yellow] (will auto-refresh on next command).")
        else:
            console.print(
                "[red]Token expired.[/red] Run [bold]orchid auth login -c <config>[/bold] to re-authenticate."
            )
            return
    else:
        console.print("[bold green]Authenticated[/bold green]")

    _print_token_info(token)


# ── Helpers ────────────────────────────────────────────────────


def _print_token_info(token: StoredToken) -> None:
    """Print token details to the console."""
    if token.expires_at > 0:
        import time

        remaining = token.expires_at - time.time()
        if remaining > 0:
            mins = int(remaining // 60)
            console.print(f"  Expires in: [bold]{mins}[/bold] minutes")
        else:
            console.print("  Status: [red]expired[/red]")

    if token.tenant_key:
        console.print(f"  Tenant: [bold]{token.tenant_key}[/bold]")
    if token.user_id:
        console.print(f"  User: [bold]{token.user_id}[/bold]")
    if token.scopes:
        console.print(f"  Scopes: {token.scopes}")

    # Show truncated token for debugging.
    masked = token.access_token[:8] + "..." + token.access_token[-4:] if len(token.access_token) > 16 else "***"
    console.print(f"  Token: {masked}")


async def _resolve_and_store_identity(cfg, token: StoredToken) -> None:
    """Try to resolve identity via IdentityResolver and persist the result."""
    import httpx

    from orchid_ai.utils import import_class

    resolver_cls = import_class(cfg.identity_resolver_class)

    async with httpx.AsyncClient(timeout=15) as http_client:
        resolver = resolver_cls(http_client=http_client)
        resolved_auth = await resolver.resolve(cfg.domain, token.access_token)

    token.tenant_key = resolved_auth.tenant_key
    token.user_id = resolved_auth.user_id

    console.print(f"  Tenant: [bold]{resolved_auth.tenant_key}[/bold]")
    console.print(f"  User: [bold]{resolved_auth.user_id}[/bold]")
