# orchid-cli — AI Context

## What This Package Is

**orchid-cli** is the Typer-based command-line interface for the Orchid multi-agent AI framework. It imports `orchid` (the library) as a dependency and provides terminal access to all chat operations, config validation, RAG indexing, and MCP server authorisation. It mirrors the full functionality of `orchid-api` but runs locally with no server, Docker, or external database required (defaults to SQLite).

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
      middleware.py   Token refresh + OrchidAuthContext builder
    commands/
      _session.py    resolve_session(config_path) -> (Orchid, OrchidAuthContext) +
                     warm_for_user — single chokepoint for bootstrap + auth + MCP warm
      _events_session.py
                     resolve_events_session(config_path) -> (Orchid, EventsRuntime)
                     used by the four event commands; raises when ``events.enabled=false``
      auth.py        login, logout, status subcommands
      chat.py        Full CRUD: create, list, delete, history, send, interactive, rename, share
      config.py      validate command (checks agents.yaml)
      external_agents.py  list configured external-agent CLI tools
      index.py       file/dir/text/json-file commands (RAG ingestion)
      mcp.py         MCP OAuth: status, revoke per-server tokens
                     (authorize flow runs through the API gateway, not the CLI)
      signals.py     Pollen ops: emit / list / show
      jobs.py        Bloom ops: list triggers, list runs per trigger
      runs.py        Bloom ops: list / show / retry / cancel
      schedules.py   Bloom ops: list / show / disable / enable
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

3. **Commands receive an `Orchid` instance.** `bootstrap()` now returns the framework's mandatory :class:`orchid_ai.Orchid` facade directly — there is no CLI-local `OrchidContext` wrapper.  Commands read `orchid.graph`, `orchid.chat_repo`, `orchid.config`, `orchid.runtime` (and `orchid.runtime.default_model` for the old `ctx.model`, `orchid.runtime.get_reader()` for the old `ctx.reader`).

4. **Default storage is SQLite** at `~/.orchid/chats.db` (no Docker, no PostgreSQL needed). Overridable via `CHAT_STORAGE_CLASS` and `CHAT_DB_DSN` env vars.

5. **No agent or framework code here.** No `OrchidAgent` subclasses, no graph wiring, no RAG logic. Those belong in `orchid/` or consumer projects.

6. **Config resolution:** CLI args > env vars > `orchid.yml` > hardcoded defaults.

7. **OAuth auth is self-contained in `auth/`.** The `auth/` subpackage handles the full OAuth 2.0 Authorization Code + PKCE flow. No OAuth logic in `chat.py`, `bootstrap.py`, or any other module. Chat commands call `get_auth_context(config_path)` which returns either a real OAuth-backed `OrchidAuthContext` or the dev fallback — callers don't know or care which. **The CLI is an independent OAuth client** — it runs its own dance against the upstream IdP.

8. **Token storage at `~/.orchid/tokens.json`.** Permissions set to `0o600` (owner-only). Tokens are keyed by `client_id`, supporting multiple providers. Refresh tokens are used automatically when the access token expires.

9. **Commands go through `commands/_session.py:resolve_session`.** Every command that needs both an `Orchid` instance and a per-user `OrchidAuthContext` calls `resolve_session(config_path)` (or its `session_context` async-context-manager wrapper), which bootstraps the framework, resolves auth, and warms `passthrough` / `oauth` MCP capability caches once per `(tenant_key, user_id)`. The interactive REPL stays alive across many turns; the warmer's idempotency check makes subsequent loop iterations a no-op. Failures in the per-user warm are logged and ignored — the chat still works, it just pays the lazy discovery cost on first tool call. `bootstrap()` itself warms `auth.mode: none` servers up front (no user identity needed).

10. **`external_agents:` in agents.yaml** — the `agents.yaml` file may include an ``external_agents:`` block declaring external CLI delegation tools. These are registered into ``TOOL_REGISTRY`` at graph build and referenced by name in ``agent.tools:`` like any built-in tool. The ``orchid external-agents list`` command displays them; the chat commands surface ``requires_approval`` HITL prompts before every delegation.

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
orchid mcp revoke    <server> --config <path>  # Revoke stored token

# Config
orchid config validate <agents.yaml>           # Validate agent config

# RAG indexing
orchid index file <path> -n <namespace> --config <path>     # Index a single file
orchid index dir  <path> -n <namespace> --config <path>     # Index a directory
orchid index text "..."  -n <namespace> --config <path>     # Index inline text
orchid index json-file <path> -n <namespace> --config <path>  # Bulk-index JSON entries

# Pollen + Bloom ops surface — local-only, requires events.enabled: true in YAML.
orchid signals emit <type> [--payload JSON|@file] [--source S] [--tenant T] [--user U] [--dedupe-key K] [--identity JSON] -c <orchid.yml>
orchid signals list [--type T] [--tenant T] [--since 15m|2h|1d|ISO] [--limit N] -c <orchid.yml>
orchid signals show <signal_id> -c <orchid.yml>

orchid jobs list -c <orchid.yml>                         # Active triggers
orchid jobs runs <trigger_id> [--status s] [--limit N] -c <orchid.yml>

orchid runs list [--status s] [--trigger-id t] [--since 1h] [--limit N] -c <orchid.yml>
orchid runs show <run_id> -c <orchid.yml>
orchid runs retry <run_id> -c <orchid.yml>               # Re-enqueue originating signal
orchid runs cancel <run_id> -c <orchid.yml>              # Best-effort cancel

orchid schedules list -c <orchid.yml>
orchid schedules show <schedule_id> -c <orchid.yml>
orchid schedules disable <schedule_id> -c <orchid.yml>
orchid schedules enable <schedule_id> -c <orchid.yml>
```

### Pollen + Bloom local-mode notes

- Every `orchid signals/jobs/runs/schedules` command runs the events
  block **locally** against the same SQLite/Postgres backend the YAML
  configures — same pattern as `orchid chat send`, NOT an HTTP client.
- Long-running producers (`SchedulerProducer`, `HTTPIngestionProducer`,
  `RelayRecoveryProducer`) declared in YAML do NOT start under the
  CLI — short-lived invocations explicitly stop them so a one-shot
  `orchid signals emit` doesn't leave a scheduler firing in the
  background. Operators wanting a long-running producer should run
  `orchid-api` instead.
- Visibility filtering (§26) is enforced at the API layer.  The CLI
  is a local operator tool; operators inspecting via the CLI already
  have direct DB access, so a parallel filter would be theatre.
- `orchid schedules disable/enable` writes to `OrchidScheduleStore`
  durably; the next `SchedulerProducer.refresh()` (or process
  restart of `orchid-api`) picks up the change.

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
| Vector backend | `chroma` | `VECTOR_BACKEND` |
| Chroma path | `~/.orchid/chroma` | `CHROMA_PATH` |
| Qdrant URL | `http://qdrant:6333` | `QDRANT_URL` |
| Embedding model | `text-embedding-3-small` | `EMBEDDING_MODEL` |
| Storage class | `orchid_ai.persistence.sqlite.OrchidSQLiteChatStorage` | `CHAT_STORAGE_CLASS` |
| Storage DSN | `~/.orchid/chats.db` | `CHAT_DB_DSN` |
| cli_rag override | When `cli_rag:` exists in YAML, it replaces `rag:` for CLI only | — |

The CLI defaults to **ChromaDB** (local, on-disk) for zero-infrastructure RAG. Set `VECTOR_BACKEND=qdrant` to use Qdrant instead (e.g. when hybrid sparse+dense search is required).

When `orchid.yml` includes a `cli_rag:` section, the CLI uses those values instead of `rag:`. This allows Docker-based examples (with `rag.vector_backend: qdrant`) to run locally via the CLI without requiring Qdrant infrastructure.

## OAuth Configuration

OAuth is configured via the `auth.cli` section in `orchid.yml`. When absent or when `auth.dev_bypass: true`, the CLI uses a dummy dev token (backward compatible).

```yaml
auth:
  dev_bypass: false
  identity_resolver_class: myapp.identity.Resolver   # optional — enriches OrchidAuthContext
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
