"""
Chat commands — full CRUD + message send with persistence.

Mirrors orchid-api chat endpoints:
    orchid chat create [--title "My Chat"]
    orchid chat list
    orchid chat delete <chat_id>
    orchid chat history <chat_id>
    orchid chat send <chat_id> "message"
    orchid chat interactive [--chat <chat_id>]
    orchid chat rename <chat_id> "new title"
    orchid chat share <chat_id>
"""

from __future__ import annotations

import asyncio
from typing import Optional

import typer
from langchain_core.messages import AIMessage, HumanMessage
from rich.console import Console
from rich.table import Table

from orchid_ai.core.state import AuthContext

from ..auth.middleware import get_auth_context
from ..bootstrap import cli_context

app = typer.Typer(help="Chat management and messaging", no_args_is_help=True)
console = Console()


# ── Chat CRUD ───────────────────────────────────────────────


@app.command()
def create(
    title: str = typer.Option("New chat", "--title", "-t", help="Chat title"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
):
    """Create a new chat session."""
    asyncio.run(_create(title, config, model))


async def _create(title: str, config_path: str, model: str) -> None:
    auth = await get_auth_context(config_path)
    async with cli_context(config_path, model=model) as ctx:
        session = await ctx.chat_repo.create_chat(
            tenant_id=auth.tenant_key,
            user_id=auth.user_id,
            title=title,
        )
        console.print(f"[bold green]Created:[/bold green] {session.id}")
        console.print(f"  Title: {session.title}")
        console.print(f"  Created: {session.created_at.isoformat()}")


@app.command("list")
def list_chats(
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
):
    """List all chat sessions."""
    asyncio.run(_list_chats(config, model))


async def _list_chats(config_path: str, model: str) -> None:
    auth = await get_auth_context(config_path)
    async with cli_context(config_path, model=model) as ctx:
        sessions = await ctx.chat_repo.list_chats(
            tenant_id=auth.tenant_key,
            user_id=auth.user_id,
        )

        if not sessions:
            console.print("[dim]No chats found. Use 'orchid chat create' to start one.[/dim]")
            return

        table = Table(title="Chat Sessions")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Title", style="white")
        table.add_column("Messages", justify="right")
        table.add_column("Updated", style="dim")
        table.add_column("Shared", justify="center")

        for s in sessions:
            messages = await ctx.chat_repo.get_messages(s.id, limit=1000)
            table.add_row(
                s.id[:12] + "…",
                s.title[:40],
                str(len(messages)),
                s.updated_at.strftime("%Y-%m-%d %H:%M"),
                "✓" if s.is_shared else "",
            )

        console.print(table)


@app.command()
def delete(
    chat_id: str = typer.Argument(..., help="Chat ID (or prefix)"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete a chat session and all its messages."""
    asyncio.run(_delete(chat_id, config, model, force))


async def _delete(chat_id: str, config_path: str, model: str, force: bool) -> None:
    auth = await get_auth_context(config_path)
    async with cli_context(config_path, model=model) as ctx:
        resolved_id = await _resolve_chat_id(ctx, chat_id, auth)
        if not resolved_id:
            return

        chat = await ctx.chat_repo.get_chat(resolved_id)
        if not force:
            confirm = typer.confirm(f"Delete chat '{chat.title}' ({resolved_id[:12]}…)?")
            if not confirm:
                console.print("[dim]Cancelled.[/dim]")
                return

        await ctx.chat_repo.delete_chat(resolved_id)
        console.print(f"[bold red]Deleted:[/bold red] {resolved_id[:12]}…")


@app.command()
def history(
    chat_id: str = typer.Argument(..., help="Chat ID (or prefix)"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max messages to show"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
):
    """Show message history for a chat."""
    asyncio.run(_history(chat_id, limit, config, model))


async def _history(chat_id: str, limit: int, config_path: str, model: str) -> None:
    auth = await get_auth_context(config_path)
    async with cli_context(config_path, model=model) as ctx:
        resolved_id = await _resolve_chat_id(ctx, chat_id, auth)
        if not resolved_id:
            return

        chat = await ctx.chat_repo.get_chat(resolved_id)
        messages = await ctx.chat_repo.get_messages(resolved_id, limit=limit)

        console.print(f"[bold]{chat.title}[/bold] ({resolved_id[:12]}…)")
        console.print()

        if not messages:
            console.print("[dim]No messages yet.[/dim]")
            return

        for msg in messages:
            if msg.role == "user":
                console.print(f"[bold cyan]You:[/bold cyan] {msg.content}")
            elif msg.role == "assistant":
                console.print(f"[bold green]Assistant:[/bold green] {msg.content}")
                if msg.agents_used:
                    console.print(f"  [dim]Agents: {', '.join(msg.agents_used)}[/dim]")
            else:
                console.print(f"[dim]{msg.role}: {msg.content}[/dim]")
            console.print()


@app.command()
def rename(
    chat_id: str = typer.Argument(..., help="Chat ID (or prefix)"),
    title: str = typer.Argument(..., help="New title"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
):
    """Rename a chat session."""
    asyncio.run(_rename(chat_id, title, config, model))


async def _rename(chat_id: str, title: str, config_path: str, model: str) -> None:
    auth = await get_auth_context(config_path)
    async with cli_context(config_path, model=model) as ctx:
        resolved_id = await _resolve_chat_id(ctx, chat_id, auth)
        if not resolved_id:
            return

        await ctx.chat_repo.update_title(resolved_id, title)
        console.print(f"[bold]Renamed:[/bold] {resolved_id[:12]}… → {title}")


@app.command()
def share(
    chat_id: str = typer.Argument(..., help="Chat ID (or prefix)"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
):
    """Mark a chat as shared."""
    asyncio.run(_share(chat_id, config, model))


async def _share(chat_id: str, config_path: str, model: str) -> None:
    auth = await get_auth_context(config_path)
    async with cli_context(config_path, model=model) as ctx:
        resolved_id = await _resolve_chat_id(ctx, chat_id, auth)
        if not resolved_id:
            return

        await ctx.chat_repo.mark_shared(resolved_id)
        console.print(f"[bold]Shared:[/bold] {resolved_id[:12]}…")


# ── Messaging ───────────────────────────────────────────────


@app.command()
def send(
    chat_id: str = typer.Argument(..., help="Chat ID (or prefix)"),
    message: str = typer.Argument(..., help="The message to send"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
):
    """Send a message to a chat and print the response."""
    asyncio.run(_send(chat_id, message, config, model))


async def _send(chat_id: str, message: str, config_path: str, model: str) -> None:
    auth = await get_auth_context(config_path)
    async with cli_context(config_path, model=model) as ctx:
        resolved_id = await _resolve_chat_id(ctx, chat_id, auth)
        if not resolved_id:
            return

        response_text, agents_used = await _send_message(ctx, resolved_id, message, auth)

        console.print()
        console.print(response_text)
        if agents_used:
            console.print(f"\n[dim]Agents used: {', '.join(agents_used)}[/dim]")


@app.command()
def interactive(
    chat_id: Optional[str] = typer.Argument(None, help="Chat ID to resume (or prefix). Creates new if omitted."),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
):
    """Start an interactive chat REPL with full persistence."""
    asyncio.run(_interactive(chat_id, config, model))


async def _interactive(chat_id: str | None, config_path: str, model: str) -> None:
    auth = await get_auth_context(config_path)
    async with cli_context(config_path, model=model) as ctx:
        # Resolve or create a chat
        if chat_id:
            resolved_id = await _resolve_chat_id(ctx, chat_id, auth)
            if not resolved_id:
                return
            chat = await ctx.chat_repo.get_chat(resolved_id)
            console.print(f"[bold]Resuming:[/bold] {chat.title} ({resolved_id[:12]}…)")
        else:
            chat = await ctx.chat_repo.create_chat(
                tenant_id=auth.tenant_key,
                user_id=auth.user_id,
                title="Interactive session",
            )
            resolved_id = chat.id
            console.print(f"[bold]New chat:[/bold] {resolved_id[:12]}…")

        console.print()
        console.print("[bold]Orchid Interactive Chat[/bold]")
        console.print("Commands: /quit, /switch <id>, /list, /new [title], /history, /rename <title>")
        console.print()

        current_chat_id = resolved_id

        while True:
            try:
                user_input = console.input("[bold cyan]You:[/bold cyan] ")
            except (EOFError, KeyboardInterrupt):
                break

            stripped = user_input.strip()
            if not stripped:
                continue

            # Handle slash commands
            if stripped.startswith("/"):
                parts = stripped.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""

                if cmd in ("/quit", "/exit", "/q"):
                    break

                elif cmd == "/list":
                    sessions = await ctx.chat_repo.list_chats(
                        tenant_id=auth.tenant_key,
                        user_id=auth.user_id,
                    )
                    if not sessions:
                        console.print("[dim]No chats.[/dim]")
                    else:
                        for s in sessions:
                            marker = " [bold]← current[/bold]" if s.id == current_chat_id else ""
                            console.print(f"  {s.id[:12]}…  {s.title}{marker}")
                    console.print()
                    continue

                elif cmd == "/switch":
                    if not arg:
                        console.print("[red]Usage: /switch <chat_id>[/red]")
                        continue
                    new_id = await _resolve_chat_id(ctx, arg, auth)
                    if new_id:
                        current_chat_id = new_id
                        chat = await ctx.chat_repo.get_chat(current_chat_id)
                        console.print(f"[bold]Switched to:[/bold] {chat.title} ({current_chat_id[:12]}…)\n")
                    continue

                elif cmd == "/new":
                    title = arg or "Interactive session"
                    new_chat = await ctx.chat_repo.create_chat(
                        tenant_id=auth.tenant_key,
                        user_id=auth.user_id,
                        title=title,
                    )
                    current_chat_id = new_chat.id
                    console.print(f"[bold green]New chat:[/bold green] {current_chat_id[:12]}… — {title}\n")
                    continue

                elif cmd == "/history":
                    messages = await ctx.chat_repo.get_messages(current_chat_id, limit=20)
                    if not messages:
                        console.print("[dim]No messages yet.[/dim]\n")
                    else:
                        for msg in messages:
                            if msg.role == "user":
                                console.print(f"  [cyan]You:[/cyan] {msg.content[:80]}")
                            elif msg.role == "assistant":
                                console.print(f"  [green]Asst:[/green] {msg.content[:80]}")
                        console.print()
                    continue

                elif cmd == "/rename":
                    if not arg:
                        console.print("[red]Usage: /rename <new title>[/red]")
                        continue
                    await ctx.chat_repo.update_title(current_chat_id, arg)
                    console.print(f"[bold]Renamed:[/bold] {arg}\n")
                    continue

                else:
                    console.print(f"[red]Unknown command: {cmd}[/red]")
                    continue

            # Send message
            response_text, agents_used = await _send_message(ctx, current_chat_id, stripped, auth)
            console.print(f"\n[bold green]Assistant:[/bold green] {response_text}")
            if agents_used:
                console.print(f"  [dim]Agents: {', '.join(agents_used)}[/dim]")
            console.print()

        console.print("\n[dim]Session ended.[/dim]")


# ── Helpers ─────────────────────────────────────────────────


async def _send_message(ctx, chat_id: str, message: str, auth: AuthContext) -> tuple[str, list[str]]:
    """Send a message through the graph, persist to storage, return (response, agents_used)."""
    # Load history
    history_rows = await ctx.chat_repo.get_messages(chat_id, limit=50)
    history_messages = []
    for row in history_rows:
        if row.role == "user":
            history_messages.append(HumanMessage(content=row.content, id=row.id))
        elif row.role == "assistant":
            history_messages.append(AIMessage(content=row.content, id=row.id))

    # Pre-flight MCP auth check — auto-trigger OAuth for unauthorized servers
    mcp_auth_status: dict[str, bool] = {}
    registry = ctx.runtime.mcp_auth_registry
    store = ctx.mcp_token_store
    if registry and not registry.empty and store:
        for name in registry.oauth_servers:
            token = await store.get_token(auth.tenant_key, auth.user_id, name)
            mcp_auth_status[name] = token is not None and not token.is_expired

        unauthorized = [name for name, ok in mcp_auth_status.items() if not ok]
        if unauthorized:
            from .mcp import _auto_authorize_servers

            authorized = await _auto_authorize_servers(unauthorized, registry, auth, store)
            for name in authorized:
                mcp_auth_status[name] = True

    initial_state: dict = {
        "messages": history_messages + [HumanMessage(content=message)],
        "auth_context": auth,
        "chat_id": chat_id,
    }
    if mcp_auth_status:
        initial_state["mcp_auth_status"] = mcp_auth_status

    result = await ctx.graph.ainvoke(initial_state)

    response_text = result.get("final_response", "No response generated.")
    agents_used = result.get("active_agents", [])

    # Persist original message + response
    await ctx.chat_repo.add_message(chat_id, "user", message)
    await ctx.chat_repo.add_message(chat_id, "assistant", response_text, agents_used=agents_used)

    # Auto-title from first message
    if not history_rows:
        title = message[:50].strip()
        if len(message) > 50:
            title += "…"
        await ctx.chat_repo.update_title(chat_id, title)

    return response_text, agents_used


async def _resolve_chat_id(ctx, chat_id_prefix: str, auth: AuthContext) -> str | None:
    """Resolve a chat ID prefix to a full ID. Prints error if not found."""
    # Try exact match first
    chat = await ctx.chat_repo.get_chat(chat_id_prefix)
    if chat and chat.user_id == auth.user_id:
        return chat.id

    # Try prefix match
    sessions = await ctx.chat_repo.list_chats(
        tenant_id=auth.tenant_key,
        user_id=auth.user_id,
    )
    matches = [s for s in sessions if s.id.startswith(chat_id_prefix)]

    if len(matches) == 1:
        return matches[0].id
    elif len(matches) > 1:
        console.print(f"[red]Ambiguous prefix '{chat_id_prefix}' — matches {len(matches)} chats:[/red]")
        for s in matches:
            console.print(f"  {s.id[:12]}…  {s.title}")
        return None
    else:
        console.print(f"[red]Chat not found: {chat_id_prefix}[/red]")
        return None
