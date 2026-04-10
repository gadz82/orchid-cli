"""Shared fixtures for orchid-cli tests."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchid_ai.core.state import AuthContext
from orchid_ai.persistence.models import ChatMessage, ChatSession
from orchid_cli.bootstrap import OrchidContext


@pytest.fixture
def mock_chat_repo():
    repo = AsyncMock()
    repo.create_chat = AsyncMock()
    repo.list_chats = AsyncMock(return_value=[])
    repo.get_chat = AsyncMock(return_value=None)
    repo.delete_chat = AsyncMock()
    repo.get_messages = AsyncMock(return_value=[])
    repo.add_message = AsyncMock()
    repo.update_title = AsyncMock()
    repo.mark_shared = AsyncMock()
    repo.close = AsyncMock()
    return repo


@pytest.fixture
def mock_graph():
    graph = AsyncMock()
    graph.ainvoke = AsyncMock(return_value={
        "final_response": "Test response",
        "active_agents": ["test_agent"],
    })
    return graph


@pytest.fixture
def mock_reader():
    return MagicMock()


@pytest.fixture
def mock_context(mock_graph, mock_reader, mock_chat_repo):
    return OrchidContext(
        graph=mock_graph,
        reader=mock_reader,
        chat_repo=mock_chat_repo,
        config=MagicMock(),
        model="test-model",
    )


@pytest.fixture
def sample_sessions():
    now = datetime.now(timezone.utc)
    return [
        ChatSession(id="aaa-111", tenant_id="cli", user_id="cli-user", title="Chat A", created_at=now, updated_at=now, is_shared=False),
        ChatSession(id="bbb-222", tenant_id="cli", user_id="cli-user", title="Chat B", created_at=now, updated_at=now, is_shared=True),
    ]


@pytest.fixture
def sample_session():
    now = datetime.now(timezone.utc)
    return ChatSession(
        id="aaa-111", tenant_id="cli", user_id="cli-user",
        title="Test Chat", created_at=now, updated_at=now, is_shared=False,
    )


@pytest.fixture
def sample_messages():
    now = datetime.now(timezone.utc)
    return [
        ChatMessage(id="m1", chat_id="aaa-111", role="user", content="Hello", agents_used=[], created_at=now),
        ChatMessage(id="m2", chat_id="aaa-111", role="assistant", content="Hi there!", agents_used=["test"], created_at=now),
    ]
