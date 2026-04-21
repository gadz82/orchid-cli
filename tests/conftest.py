"""Shared fixtures for orchid-cli tests."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchid_ai.persistence.models import OrchidChatMessage, OrchidChatSession


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
    graph.ainvoke = AsyncMock(
        return_value={
            "final_response": "Test response",
            "active_agents": ["test_agent"],
        }
    )
    return graph


@pytest.fixture
def mock_reader():
    return MagicMock()


@pytest.fixture
def mock_context(mock_graph, mock_reader, mock_chat_repo):
    """A stand-in for the ``Orchid`` facade — exposes the same public
    attributes used by CLI commands (``graph``, ``chat_repo``, ``config``,
    ``mcp_token_store``, ``runtime``)."""
    runtime = MagicMock()
    runtime.default_model = "test-model"
    runtime.get_reader.return_value = mock_reader
    runtime.mcp_auth_registry = MagicMock()
    runtime.checkpointer = None

    orchid = MagicMock()
    orchid.graph = mock_graph
    orchid.chat_repo = mock_chat_repo
    orchid.config = MagicMock()
    orchid.mcp_token_store = None
    orchid.runtime = runtime
    return orchid


@pytest.fixture
def sample_sessions():
    now = datetime.now(timezone.utc)
    return [
        OrchidChatSession(
            id="aaa-111",
            tenant_id="cli",
            user_id="cli-user",
            title="Chat A",
            created_at=now,
            updated_at=now,
            is_shared=False,
        ),
        OrchidChatSession(
            id="bbb-222",
            tenant_id="cli",
            user_id="cli-user",
            title="Chat B",
            created_at=now,
            updated_at=now,
            is_shared=True,
        ),
    ]


@pytest.fixture
def sample_session():
    now = datetime.now(timezone.utc)
    return OrchidChatSession(
        id="aaa-111",
        tenant_id="cli",
        user_id="cli-user",
        title="Test Chat",
        created_at=now,
        updated_at=now,
        is_shared=False,
    )


@pytest.fixture
def sample_messages():
    now = datetime.now(timezone.utc)
    return [
        OrchidChatMessage(id="m1", chat_id="aaa-111", role="user", content="Hello", agents_used=[], created_at=now),
        OrchidChatMessage(
            id="m2", chat_id="aaa-111", role="assistant", content="Hi there!", agents_used=["test"], created_at=now
        ),
    ]
