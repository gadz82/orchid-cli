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

The send/stream pipeline lives in :mod:`._chat_send`; the REPL and
slash-command machinery live in :mod:`._chat_interactive`. This module
owns only the Typer surface.
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from .._typer_async import async_command
from ._chat_helpers import resolve_chat_id
from ._chat_interactive import register_builtin_slash_commands, run_repl
from ._chat_send import send_message
from ._session import session_context

# Re-run the built-in slash registration on every (re-)import of this
# module. The handlers themselves are owned by ``_chat_interactive``, but
# integrators that reload ``commands.chat`` to refresh plugins expect
# the built-ins to come back too.
register_builtin_slash_commands()

app = typer.Typer(help="Chat management and messaging", no_args_is_help=True)
console = Console()


# ── Chat CRUD ───────────────────────────────────────────────


@app.command()
@async_command
async def create(
    title: str = typer.Option("New chat", "--title", "-t", help="Chat title"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
) -> None:
    """Create a new chat session."""
    async with session_context(config, model=model) as (ctx, auth):
        session = await ctx.chat_repo.create_chat(
            tenant_id=auth.tenant_key,
            user_id=auth.user_id,
            title=title,
        )
        console.print(f"[bold green]Created:[/bold green] {session.id}")
        console.print(f"  Title: {session.title}")
        console.print(f"  Created: {session.created_at.isoformat()}")


@app.command("list")
@async_command
async def list_chats(
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
) -> None:
    """List all chat sessions."""
    async with session_context(config, model=model) as (ctx, auth):
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
@async_command
async def delete(
    chat_id: str = typer.Argument(..., help="Chat ID (or prefix)"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Delete a chat session and all its messages."""
    async with session_context(config, model=model) as (ctx, auth):
        resolved_id = await resolve_chat_id(ctx, chat_id, auth)
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
@async_command
async def history(
    chat_id: str = typer.Argument(..., help="Chat ID (or prefix)"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max messages to show"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
) -> None:
    """Show message history for a chat."""
    async with session_context(config, model=model) as (ctx, auth):
        resolved_id = await resolve_chat_id(ctx, chat_id, auth)
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
                # Assistant replies may contain Markdown (bold, lists,
                # fenced code); render them so the history view matches
                # what the live interactive session showed.
                console.print("[bold green]Assistant:[/bold green]")
                console.print(Markdown(msg.content))
                if msg.agents_used:
                    console.print(f"  [dim]Agents: {', '.join(msg.agents_used)}[/dim]")
                cancelled = (msg.metadata or {}).get("cancelled", False)
                if cancelled:
                    console.print("  [dim red]⏹ Cancelled[/dim red]")
            else:
                console.print(f"[dim]{msg.role}: {msg.content}[/dim]")
            console.print()


@app.command()
@async_command
async def rename(
    chat_id: str = typer.Argument(..., help="Chat ID (or prefix)"),
    title: str = typer.Argument(..., help="New title"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
) -> None:
    """Rename a chat session."""
    async with session_context(config, model=model) as (ctx, auth):
        resolved_id = await resolve_chat_id(ctx, chat_id, auth)
        if not resolved_id:
            return

        await ctx.chat_repo.update_title(resolved_id, title)
        console.print(f"[bold]Renamed:[/bold] {resolved_id[:12]}… → {title}")


@app.command()
@async_command
async def share(
    chat_id: str = typer.Argument(..., help="Chat ID (or prefix)"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
) -> None:
    """Mark a chat as shared."""
    async with session_context(config, model=model) as (ctx, auth):
        resolved_id = await resolve_chat_id(ctx, chat_id, auth)
        if not resolved_id:
            return

        await ctx.chat_repo.mark_shared(resolved_id)
        console.print(f"[bold]Shared:[/bold] {resolved_id[:12]}…")


# ── Messaging ───────────────────────────────────────────────


@app.command()
@async_command
async def send(
    chat_id: str = typer.Argument(..., help="Chat ID (or prefix)"),
    message: str = typer.Argument(..., help="The message to send"),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
    content_path: list[str] = typer.Option([], "--content-path", help="Path(s) to content directories (repeatable)"),
) -> None:
    """Send a message to a chat and print the response."""
    async with session_context(config, model=model, content_paths=content_path or None) as (ctx, auth):
        resolved_id = await resolve_chat_id(ctx, chat_id, auth)
        if not resolved_id:
            return

        response_text, agents_used = await send_message(ctx, resolved_id, message, auth)

        console.print()
        # Render the final response as Markdown so ``**bold**``, lists, and
        # fenced code blocks surface correctly in the terminal.
        console.print(Markdown(response_text))
        if agents_used:
            console.print(f"\n[dim]Agents used: {', '.join(agents_used)}[/dim]")


@app.command()
@async_command
async def interactive(
    chat_id: Optional[str] = typer.Argument(None, help="Chat ID to resume (or prefix). Creates new if omitted."),
    config: str = typer.Option("", "--config", "-c", help="Path to orchid.yml"),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model"),
    content_path: list[str] = typer.Option([], "--content-path", help="Path(s) to content directories (repeatable)"),
) -> None:
    """Start an interactive chat REPL with full persistence."""
    await run_repl(chat_id, config, model, content_paths=content_path or None)
