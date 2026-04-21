"""Tests for orchid_cli.commands.chat — chat CRUD and messaging helpers."""

from __future__ import annotations

import pytest

from orchid_ai.core.state import OrchidAuthContext

from orchid_cli.commands.chat import _resolve_chat_id, _send_message

# Shared test auth context — matches the legacy _CLI_AUTH defaults.
_TEST_AUTH = OrchidAuthContext(access_token="cli-token", tenant_key="cli", user_id="cli-user")


# ── _resolve_chat_id ───────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_exact_match(mock_context, sample_session):
    """Exact chat ID match returns the ID."""
    sample_session.user_id = "cli-user"
    mock_context.chat_repo.get_chat.return_value = sample_session
    result = await _resolve_chat_id(mock_context, "aaa-111", _TEST_AUTH)
    assert result == "aaa-111"


@pytest.mark.asyncio
async def test_resolve_prefix_match(mock_context, sample_sessions):
    """Unique prefix match returns the full ID."""
    mock_context.chat_repo.get_chat.return_value = None
    mock_context.chat_repo.list_chats.return_value = sample_sessions
    result = await _resolve_chat_id(mock_context, "aaa", _TEST_AUTH)
    assert result == "aaa-111"


@pytest.mark.asyncio
async def test_resolve_ambiguous_prefix(mock_context, sample_sessions, capsys):
    """Ambiguous prefix returns None."""
    # Both sessions start with different prefixes, but let's make them ambiguous
    sample_sessions[1].id = "aaa-222"  # now both start with "aaa"
    mock_context.chat_repo.get_chat.return_value = None
    mock_context.chat_repo.list_chats.return_value = sample_sessions
    result = await _resolve_chat_id(mock_context, "aaa", _TEST_AUTH)
    assert result is None


@pytest.mark.asyncio
async def test_resolve_not_found(mock_context, capsys):
    """Non-existent ID returns None."""
    mock_context.chat_repo.get_chat.return_value = None
    mock_context.chat_repo.list_chats.return_value = []
    result = await _resolve_chat_id(mock_context, "zzz", _TEST_AUTH)
    assert result is None


# ── _send_message ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_message_returns_response(mock_context):
    """send_message invokes graph and returns response + agents."""
    mock_context.chat_repo.get_messages.return_value = []
    response, agents = await _send_message(mock_context, "chat-1", "Hello", _TEST_AUTH)
    assert response == "Test response"
    assert agents == ["test_agent"]


@pytest.mark.asyncio
async def test_send_message_persists_messages(mock_context):
    """Both user message and assistant response are persisted."""
    mock_context.chat_repo.get_messages.return_value = []
    await _send_message(mock_context, "chat-1", "Hello", _TEST_AUTH)
    calls = mock_context.chat_repo.add_message.call_args_list
    assert len(calls) == 2
    # First call: user message
    assert calls[0].args == ("chat-1", "user", "Hello")
    # Second call: assistant response
    assert calls[1].args == ("chat-1", "assistant", "Test response")


@pytest.mark.asyncio
async def test_send_message_auto_titles_first_message(mock_context):
    """First message in a chat auto-generates a title."""
    mock_context.chat_repo.get_messages.return_value = []  # no history = first message
    await _send_message(mock_context, "chat-1", "Tell me about LeBron James", _TEST_AUTH)
    mock_context.chat_repo.update_title.assert_called_once()
    title_arg = mock_context.chat_repo.update_title.call_args.args[1]
    assert "LeBron" in title_arg


@pytest.mark.asyncio
async def test_send_message_no_auto_title_with_history(mock_context, sample_messages):
    """Subsequent messages do NOT auto-title."""
    mock_context.chat_repo.get_messages.return_value = sample_messages
    await _send_message(mock_context, "chat-1", "Follow up question", _TEST_AUTH)
    mock_context.chat_repo.update_title.assert_not_called()


@pytest.mark.asyncio
async def test_send_message_truncates_long_title(mock_context):
    """Auto-title is truncated to 50 chars with ellipsis."""
    mock_context.chat_repo.get_messages.return_value = []
    long_msg = "A" * 100
    await _send_message(mock_context, "chat-1", long_msg, _TEST_AUTH)
    title_arg = mock_context.chat_repo.update_title.call_args.args[1]
    assert len(title_arg) <= 52  # 50 chars + "…"
