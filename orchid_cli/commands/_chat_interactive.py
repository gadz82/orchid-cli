"""Interactive REPL plus the built-in slash-command handlers.

The CLI ``orchid chat interactive`` subcommand calls :func:`run_repl`;
the slash-command handlers are registered with the global slash
registry the first time this module is imported.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console

from ..slash_commands import (
    SlashContext,
    get_slash_command,
    list_slash_commands,
    register_slash_command,
)
from ._chat_helpers import resolve_chat_id
from ._chat_send import send_message
from ._session import session_context

console = Console()


# ── Built-in slash commands ─────────────────────────────────


async def _cmd_list(sc: SlashContext) -> str | None:
    sessions = await sc.ctx.chat_repo.list_chats(tenant_id=sc.auth.tenant_key, user_id=sc.auth.user_id)
    if not sessions:
        sc.console.print("[dim]No chats.[/dim]")
    else:
        for s in sessions:
            marker = " [bold]← current[/bold]" if s.id == sc.current_chat_id else ""
            sc.console.print(f"  {s.id[:12]}…  {s.title}{marker}")
    sc.console.print()
    return None


async def _cmd_switch(sc: SlashContext) -> str | None:
    if not sc.arg:
        sc.console.print("[red]Usage: /switch <chat_id>[/red]")
        return None
    new_id = await resolve_chat_id(sc.ctx, sc.arg, sc.auth)
    if new_id:
        chat = await sc.ctx.chat_repo.get_chat(new_id)
        sc.console.print(f"[bold]Switched to:[/bold] {chat.title} ({new_id[:12]}…)\n")
        return new_id
    return None


async def _cmd_new(sc: SlashContext) -> str | None:
    title = sc.arg or "Interactive session"
    new_chat = await sc.ctx.chat_repo.create_chat(
        tenant_id=sc.auth.tenant_key,
        user_id=sc.auth.user_id,
        title=title,
    )
    sc.console.print(f"[bold green]New chat:[/bold green] {new_chat.id[:12]}… — {title}\n")
    return new_chat.id


async def _cmd_history(sc: SlashContext) -> str | None:
    messages = await sc.ctx.chat_repo.get_messages(sc.current_chat_id, limit=20)
    if not messages:
        sc.console.print("[dim]No messages yet.[/dim]\n")
    else:
        for msg in messages:
            if msg.role == "user":
                sc.console.print(f"  [cyan]You:[/cyan] {msg.content[:80]}")
            elif msg.role == "assistant":
                sc.console.print(f"  [green]Asst:[/green] {msg.content[:80]}")
        sc.console.print()
    return None


async def _cmd_rename(sc: SlashContext) -> str | None:
    if not sc.arg:
        sc.console.print("[red]Usage: /rename <new title>[/red]")
        return None
    await sc.ctx.chat_repo.update_title(sc.current_chat_id, sc.arg)
    sc.console.print(f"[bold]Renamed:[/bold] {sc.arg}\n")
    return None


# Built-in slash commands registered at import time.  We guard against
# double-registration (happens under ``importlib.reload`` and in some
# pytest collection modes) by relying on ``register_slash_command``
# replacing prior entries with the same name — integrator-added commands
# under different names are kept.
_BUILTIN_SLASH_COMMANDS: tuple[tuple[str, Any, str], ...] = (
    ("/list", _cmd_list, "List chats"),
    ("/switch", _cmd_switch, "Switch to another chat (by prefix)"),
    ("/new", _cmd_new, "Create a new chat"),
    ("/history", _cmd_history, "Show recent messages"),
    ("/rename", _cmd_rename, "Rename the current chat"),
)


def register_builtin_slash_commands() -> None:
    """Register the chat module's built-in slash commands (idempotent)."""
    for name, handler, help_text in _BUILTIN_SLASH_COMMANDS:
        register_slash_command(name, handler, help=help_text)


register_builtin_slash_commands()


async def _dispatch_slash_command(
    ctx,
    cmd: str,
    arg: str,
    current_chat_id: str,
    auth,
) -> str | None:
    """Dispatch a slash command via the registry. Returns new chat_id if changed, else None."""
    entry = get_slash_command(cmd)
    if entry is None:
        console.print(f"[red]Unknown command: {cmd}[/red]")
        return None
    sc = SlashContext(
        ctx=ctx,
        arg=arg,
        current_chat_id=current_chat_id,
        auth=auth,
        console=console,
    )
    return await entry.handler(sc)


# ── REPL ───────────────────────────────────────────────────


async def run_repl(chat_id: str | None, config_path: str, model: str) -> None:
    """Resolve the session, optionally pick a chat, then run the REPL loop."""
    async with session_context(config_path, model=model) as (ctx, auth):
        if chat_id:
            resolved_id = await resolve_chat_id(ctx, chat_id, auth)
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
        registered = ", ".join(entry.name for entry in list_slash_commands())
        console.print(f"Commands: /quit, {registered}")
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

            if stripped.startswith("/"):
                parts = stripped.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""

                if cmd in ("/quit", "/exit", "/q"):
                    break

                result = await _dispatch_slash_command(ctx, cmd, arg, current_chat_id, auth)
                if result is not None:
                    current_chat_id = result  # /switch and /new update the active chat
                continue

            # Send message (streaming in interactive mode for real-time output).
            console.print("\n[bold green]Assistant:[/bold green]")
            response_text, agents_used = await send_message(ctx, current_chat_id, stripped, auth, streaming=True)
            if agents_used:
                console.print(f"  [dim]Agents: {', '.join(agents_used)}[/dim]")
            console.print()

        console.print("\n[dim]Session ended.[/dim]")
