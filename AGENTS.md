# orchid-cli — AI Context

## What This Package Is

**orchid-cli** is the Typer-based command-line interface for the Orchid multi-agent AI framework. It imports `orchid` (the library) as a dependency and provides terminal access to all chat operations, config validation, RAG indexing, and Claude Code skill generation. It mirrors the full functionality of `orchid-api` but runs locally with no server, Docker, or external database required (defaults to SQLite).

## Package Structure

```
orchid-cli/
  orchid_cli/
    main.py          Typer entry point — registers sub-commands
    bootstrap.py     Shared startup: load config, build graph, init SQLite storage
    commands/
      chat.py        Full CRUD: create, list, delete, history, send, interactive, rename, share
      config.py      validate command (checks agents.yaml)
      index.py       seed command (batch-index RAG data)
      skill.py       generate command (Claude Code skills from agents.yaml)
  pyproject.toml
```

## Key Dependencies

| Package | Role |
|---------|------|
| `orchid` | Core framework (agents, graph, RAG, persistence) |
| `typer` | CLI framework |
| `rich` | Terminal formatting |
| `pyyaml` | YAML config loading |
| `pydantic-settings` | Environment config |
| `httpx` | Async HTTP (for MCP calls) |
| `langchain-core` | LangGraph message types |

## Architecture Rules (Apply When Editing This Package)

1. **This is a thin CLI layer.** It calls `orchid` SDK functions and displays results. Business logic belongs in `orchid/`, not here.

2. **`bootstrap.py` mirrors `orchid-api/main.py:lifespan()`.** Both load config, build the graph, and initialize storage. Keep them in sync when adding new startup steps.

3. **`OrchidContext` dataclass holds runtime state.** Created once by `bootstrap()`, passed to commands. Contains: `graph`, `reader`, `chat_repo`, `config`, `model`.

4. **Default storage is SQLite** at `~/.orchid/chats.db` (no Docker, no PostgreSQL needed). Overridable via `CHAT_STORAGE_CLASS` and `CHAT_DB_DSN` env vars.

5. **No agent or framework code here.** No `BaseAgent` subclasses, no graph wiring, no RAG logic. Those belong in `orchid/` or consumer projects.

6. **Config resolution:** CLI args > env vars > `orchid.yml` > hardcoded defaults.

## Commands

```bash
# Chat operations
orchid chat create    --config <path>          # Create new chat session
orchid chat list      --config <path>          # List all chats
orchid chat delete    --config <path> <id>     # Delete a chat
orchid chat history   --config <path> <id>     # Show chat messages
orchid chat send      --config <path> "msg"    # Send single message
orchid chat interactive --config <path>        # Interactive REPL mode
orchid chat rename    --config <path> <id>     # Rename a chat
orchid chat share     --config <path> <id>     # Promote RAG to user scope

# Config
orchid config validate <agents.yaml>           # Validate agent config

# RAG indexing
orchid index seed     --config <path>          # Batch-index RAG data

# Skill generation (Claude Code)
orchid skill generate <agents.yaml>            # Generate Claude Code skills
orchid skill generate <agents.yaml> -o ./out   # Custom output directory
orchid skill generate <agents.yaml> --include agent1,agent2  # Filter by name
orchid skill generate <agents.yaml> --overwrite              # Overwrite existing
orchid skill generate <agents.yaml> --zip                    # Create zip archive
```

### Interactive Mode Slash Commands

| Command | Purpose |
|---------|---------|
| `/switch <id>` | Switch to another chat |
| `/list` | List all chats |
| `/new` | Create new chat |
| `/history` | Show current chat history |
| `/rename <name>` | Rename current chat |
| `/quit` | Exit interactive mode |

Chat ID prefix matching is supported (type first few chars of UUID).

## Bootstrap Defaults

| Parameter | Default | Env Override |
|-----------|---------|-------------|
| LLM model | `ollama/llama3.2` | `LITELLM_MODEL` |
| Vector backend | `qdrant` | `VECTOR_BACKEND` |
| Qdrant URL | `http://qdrant:6333` | `QDRANT_URL` |
| Embedding model | `text-embedding-3-small` | `EMBEDDING_MODEL` |
| Storage class | `orchid.persistence.sqlite.SQLiteChatStorage` | `CHAT_STORAGE_CLASS` |
| Storage DSN | `~/.orchid/chats.db` | `CHAT_DB_DSN` |

## Running

```bash
# Install:
pip install -e ../orchid -e .

# Quick test:
orchid chat send "Tell me about LeBron" --config ../examples/basketball/orchid.yml

# Interactive session:
orchid chat interactive --config ../examples/basketball/orchid.yml

# Validate config:
orchid config validate ../examples/basketball/agents.yaml
```

Requires Ollama running on host with models: `llama3.2`, `nomic-embed-text`.

## Code Style

- Python 3.11+, Ruff, line length 120
- `from __future__ import annotations` in every file
- Imports: `from orchid.xxx` (never `from src.xxx`)
- All async operations use `asyncio.run()` or Typer's async support
- No vendor-specific code — platform integrations belong in consumers

## Common Pitfalls

- The `--config` flag points to `orchid.yml` (top-level config), not `agents.yaml`. The agents config path is resolved from `AGENTS_CONFIG_PATH` inside `orchid.yml`.
- `bootstrap()` sets `ORCHID_CONFIG` as an env var so the orchid library can find the YAML. Don't remove this.
- Chat persistence auto-creates `~/.orchid/chats.db` on first run. The directory is created automatically.
- Embedding dimension mismatch (768 vs 1536 vs 3072) causes silent retrieval failures. Switching models requires re-indexing Qdrant.
