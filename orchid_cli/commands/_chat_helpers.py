"""Shared helpers used by every chat sub-module."""

from __future__ import annotations

from rich.console import Console

from orchid_ai.core.state import OrchidAuthContext

console = Console()


async def resolve_chat_id(ctx, chat_id_prefix: str, auth: OrchidAuthContext) -> str | None:
    """Resolve a chat ID prefix to a full ID. Prints error if not found."""
    chat = await ctx.chat_repo.get_chat(chat_id_prefix)
    if chat and chat.user_id == auth.user_id:
        return chat.id

    sessions = await ctx.chat_repo.list_chats(
        tenant_id=auth.tenant_key,
        user_id=auth.user_id,
    )
    matches = [s for s in sessions if s.id.startswith(chat_id_prefix)]

    if len(matches) == 1:
        return matches[0].id
    if len(matches) > 1:
        console.print(f"[red]Ambiguous prefix '{chat_id_prefix}' — matches {len(matches)} chats:[/red]")
        for s in matches:
            console.print(f"  {s.id[:12]}…  {s.title}")
        return None
    console.print(f"[red]Chat not found: {chat_id_prefix}[/red]")
    return None
