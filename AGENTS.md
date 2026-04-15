# orchid-cli — AI Context

## What This Package Is

**orchid-cli** is the Typer-based command-line interface for the Orchid multi-agent AI framework. It imports `orchid` (the library) as a dependency and provides terminal access to all chat operations, config validation, RAG indexing, and Claude Code skill generation. It mirrors the full functionality of `orchid-api` but runs locally with no server, Docker, or external database required (defaults to SQLite).

## Package Structure

```
orchid-cli/
  orchid_cli/
    main.py          Typer entry point — registers sub-commands
    bootstrap.py     Shared startup: load config, build graph, init SQLite storage
    auth/            OAuth 2.0 authentication (Authorization Code + PKCE)
      config.py      OAuth provider settings from orchid.yml (OIDC discovery)
      flow.py        PKCE flow: browser login, localhost callback, code exchange
      token_store.py Secure token persistence (~/.orchid/tokens.json)
      middleware.py   Token refresh + AuthContext builder
    commands/
      auth.py        login, logout, status subcommands
      chat.py        Full CRUD: create, list, delete, history, send, interactive, rename, share
      config.py      validate command (checks agents.yaml)
      index.py       seed command (batch-index RAG data)
      mcp.py         MCP OAuth: authorize, status, revoke per-server tokens
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

7. **OAuth auth is self-contained in `auth/`.** The `auth/` subpackage handles the full OAuth 2.0 Authorization Code + PKCE flow. No OAuth logic in `chat.py`, `bootstrap.py`, or any other module. Chat commands call `get_auth_context(config_path)` which returns either a real OAuth-backed `AuthContext` or the dev fallback — callers don't know or care which.

8. **Token storage at `~/.orchid/tokens.json`.** Permissions set to `0o600` (owner-only). Tokens are keyed by `client_id`, supporting multiple providers. Refresh tokens are used automatically when the access token expires.

## Commands

```bash
# Authentication (OAuth 2.0)
orchid auth login  --config <path>             # Opens browser for OAuth login
orchid auth status --config <path>             # Show current auth state
orchid auth logout --config <path>             # Clear stored tokens

# Chat operations
orchid chat create    --config <path>          # Create new chat session
orchid chat list      --config <path>          # List all chats
orchid chat delete    --config <path> <id>     # Delete a chat
orchid chat history   --config <path> <id>     # Show chat messages
orchid chat send      --config <path> "msg"    # Send single message
orchid chat interactive --config <path>        # Interactive REPL mode
orchid chat rename    --config <path> <id>     # Rename a chat
orchid chat share     --config <path> <id>     # Promote RAG to user scope

# MCP server OAuth
orchid mcp status    --config <path>           # Show OAuth status for MCP servers
orchid mcp authorize <server> --config <path>  # Authorize via browser (PKCE)
orchid mcp revoke    <server> --config <path>  # Revoke stored token

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
| Storage class | `orchid_ai.persistence.sqlite.SQLiteChatStorage` | `CHAT_STORAGE_CLASS` |
| Storage DSN | `~/.orchid/chats.db` | `CHAT_DB_DSN` |

## OAuth Configuration

OAuth is configured via the `auth.cli` section in `orchid.yml`. When absent or when `auth.dev_bypass: true`, the CLI uses a dummy dev token (backward compatible).

```yaml
auth:
  dev_bypass: false
  identity_resolver_class: myapp.identity.Resolver   # optional — enriches AuthContext
  domain: platform.example.com                        # optional — passed to resolver

  cli:
    client_id: my-cli-app
    scopes: openid api

    # Option A: OIDC auto-discovery (recommended)
    issuer: https://auth.example.com

    # Option B: Explicit endpoints
    # authorization_endpoint: https://auth.example.com/oauth2/authorize
    # token_endpoint: https://auth.example.com/oauth2/token
```

**Flow:** `orchid auth login` opens the browser → user authenticates → callback on `localhost` → code exchanged for tokens → stored at `~/.orchid/tokens.json`. All subsequent `orchid chat` commands use the stored token automatically, refreshing it when expired.

**Auth resolution order in chat commands:** stored OAuth token → refresh if expired → identity resolver (optional) → fallback to dev token.

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
- Imports: `from orchid_ai.xxx` (never `from src.xxx`)
- All async operations use `asyncio.run()` or Typer's async support
- No vendor-specific code — platform integrations belong in consumers

## Common Pitfalls

- The `--config` flag points to `orchid.yml` (top-level config), not `agents.yaml`. The agents config path is resolved from `AGENTS_CONFIG_PATH` inside `orchid.yml`.
- `bootstrap()` sets `ORCHID_CONFIG` as an env var so the orchid library can find the YAML. Don't remove this.
- Chat persistence auto-creates `~/.orchid/chats.db` on first run. The directory is created automatically.
- Embedding dimension mismatch (768 vs 1536 vs 3072) causes silent retrieval failures. Switching models requires re-indexing Qdrant.
- Running `orchid chat` against a config with OAuth-protected MCP servers without `orchid auth login` first — the CLI falls back to the dev token, and MCP servers return 401. Always run `orchid auth login -c <config>` first.
- Token file permissions — `~/.orchid/tokens.json` should be `0o600` (owner-only). The CLI sets this automatically, but manual edits or copies may loosen permissions.
