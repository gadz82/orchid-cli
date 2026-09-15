"""Shared fixtures for orchid-cli tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from orchid_ai.persistence.models import OrchidChatMessage, OrchidChatSession


@pytest.fixture(autouse=True)
def _isolate_env():
    """Snapshot and restore ``os.environ`` around every test.

    ``bootstrap()`` / ``apply_cli_config()`` mutate ``os.environ``
    directly (e.g. ``VECTOR_BACKEND``, ``CHROMA_PATH``, ``QDRANT_URL``).
    Without this fixture those mutations leak into subsequent tests,
    causing order-dependent failures.
    """
    original_env = dict(os.environ)
    yield
    for key in set(os.environ.keys()) - set(original_env.keys()):
        del os.environ[key]
    for key, value in original_env.items():
        if os.environ.get(key) != value:
            os.environ[key] = value


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
    now = datetime.now(UTC)
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
    now = datetime.now(UTC)
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
    now = datetime.now(UTC)
    return [
        OrchidChatMessage(id="m1", chat_id="aaa-111", role="user", content="Hello", agents_used=[], created_at=now),
        OrchidChatMessage(
            id="m2", chat_id="aaa-111", role="assistant", content="Hi there!", agents_used=["test"], created_at=now
        ),
    ]
