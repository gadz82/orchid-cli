<p align="center">
  <img src="icon.svg" alt="Orchid" width="80" />
</p>

<h1 align="center">Orchid CLI</h1>

Command-line interface for the [Orchid](https://github.com/gadz82/orchid) multi-agent AI framework.

Provides terminal access to all chat operations, configuration validation, RAG indexing, and Claude Code skill generation. Mirrors the full functionality of [orchid-api](../orchid-api) but runs locally with no server, Docker, or external database required (defaults to SQLite).

## Installation

```bash
pip install orchid-ai orchid-cli
```

The `orchid` command is available after installation.

## Quick Start

```bash
# Validate config:
orchid config validate agents.yaml

# Authenticate (required for configs with OAuth-protected MCP servers):
orchid auth login -c orchid.yml

# Start an interactive chat session:
orchid chat interactive -c orchid.yml

# Send a single message:
orchid chat create -c orchid.yml -t "My Chat"
orchid chat send <chat_id> "Hello!" -c orchid.yml
```

## Commands

### Authentication

```bash
# Log in via OAuth (opens browser, exchanges code for tokens)
orchid auth login -c orchid.yml

# Check current auth status (token expiry, tenant, user)
orchid auth status -c orchid.yml

# Clear stored tokens
orchid auth logout -c orchid.yml
```

Authentication is required when MCP servers or tools need a real Bearer token. When OAuth is not configured (`auth.dev_bypass: true` or no `auth.cli` section), a dev fallback token is used automatically.

### Chat Management

```bash
# Create a new chat session
orchid chat create -c orchid.yml -t "My Chat Title"

# List all chat sessions
orchid chat list -c orchid.yml

# Show message history
orchid chat history <chat_id> -c orchid.yml
orchid chat history <chat_id> -c orchid.yml --limit 10

# Rename a chat
orchid chat rename <chat_id> "New Title" -c orchid.yml

# Share a chat (promote RAG data to user scope)
orchid chat share <chat_id> -c orchid.yml

# Delete a chat
orchid chat delete <chat_id> -c orchid.yml
orchid chat delete <chat_id> -c orchid.yml --force
```

Chat IDs support **prefix matching** -- type the first few characters of the UUID.

### Messaging

```bash
# Send a single message and print the response
orchid chat send <chat_id> "What is LangGraph?" -c orchid.yml

# Override the LLM model
orchid chat send <chat_id> "Explain RAG" -c orchid.yml -m ollama/llama3.2
```

### Interactive Mode

```bash
# Start a new interactive session
orchid chat interactive -c orchid.yml

# Resume an existing chat
orchid chat interactive <chat_id> -c orchid.yml
```

Slash commands available inside interactive mode:

| Command | Purpose |
|---------|---------|
| `/list` | List all chat sessions |
| `/switch <id>` | Switch to another chat |
| `/new [title]` | Create a new chat |
| `/history` | Show last 20 messages |
| `/rename <title>` | Rename current chat |
| `/quit` | Exit interactive mode |

### Configuration

```bash
# Validate an agents.yaml file
orchid config validate path/to/agents.yaml
```

### MCP Server Authorization

Manage per-server OAuth for MCP servers that declare `auth.mode: oauth` in `agents.yaml`.

```bash
# Show authorization status for every OAuth-enabled MCP server
orchid mcp status -c orchid.yml

# Authorize a specific MCP server via browser (PKCE flow)
orchid mcp authorize <server-name> -c orchid.yml
orchid mcp authorize <server-name> -c orchid.yml --timeout 180

# Revoke the stored token for a server
orchid mcp revoke <server-name> -c orchid.yml
```

Chat commands also **auto-authorize** any unauthorized MCP servers on first use — the CLI opens the browser, waits for consent, stores the token, and proceeds.

### RAG Indexing

Seed the vector store with data, **on startup or any time later**:

```bash
# Run the registered StaticIndexer (consumer-provided seed data)
orchid index seed -c orchid.yml --tenant my-tenant

# Index a single document (PDF, DOCX, XLSX, CSV, TXT, MD, PNG, JPG)
orchid index file ./docs/faq.pdf -n support -c orchid.yml

# Recursively index all supported files in a directory
orchid index dir ./docs -n knowledge_base -c orchid.yml
orchid index dir ./docs -n knowledge_base --pattern '*.md' -c orchid.yml

# Index a single block of inline text (no chunking)
orchid index text "Support hours are 9-5 EST Mon-Fri." \
    -n support --title "Support Hours" -c orchid.yml

# Bulk-index documents from a JSON file
orchid index json-file faqs.json -n support -c orchid.yml
```

**JSON format** for `json-file`:

```json
[
  {"id": "ref-1", "content": "Refund policy is 30 days...",
   "metadata": {"category": "billing"}},
  {"content": "2FA setup: Account > Security > Enable 2FA..."}
]
```

**Shared flags for all index subcommands:**

| Flag | Purpose | Default |
|------|---------|---------|
| `--namespace` / `-n` | Target vector store collection (**required** except for `seed`) | — |
| `--config` / `-c` | Path to `orchid.yml` | `""` |
| `--tenant` / `-t` | Tenant ID (use `__shared__` for cross-tenant seed data) | `"default"` |
| `--scope` / `-s` | Scope level: `tenant` \| `shared` \| `user` | `"tenant"` |
| `--user` | User ID (required when `--scope user`) | `""` |

**File/dir-specific flags:**

| Flag | Purpose | Default |
|------|---------|---------|
| `--chunk-size` | Characters per chunk | 1000 |
| `--chunk-overlap` | Chunk overlap | 200 |
| `--vision-model` | Vision LLM for image parsing (e.g. `ollama/minicpm-v`) | `""` |
| `--pattern` | Glob filter (dir only) | all supported extensions |

The `file` and `dir` commands use the same ingestion pipeline as the orchid-api `/upload` endpoint (parse → chunk → embed → store). The `text` and `json-file` commands skip chunking and store documents as-is.

### Skill Generation (Claude Code)

Generate [Claude Code skills](https://docs.anthropic.com/en/docs/claude-code/skills) from your Orchid agent configuration. Each agent and orchestrator skill becomes a Claude Code skill directory with a `SKILL.md` file.

```bash
# Generate skills for all agents and orchestrator skills
orchid skill generate path/to/agents.yaml

# Custom output directory
orchid skill generate path/to/agents.yaml -o .claude/skills

# Generate only specific agents/skills
orchid skill generate path/to/agents.yaml --include basketball,psychologist

# Overwrite existing skill directories
orchid skill generate path/to/agents.yaml --overwrite

# Create a zip archive for upload
orchid skill generate path/to/agents.yaml --zip
```

**What gets converted:**

| Orchid Concept | Claude Code Skill |
|---|---|
| Agent prompt | Core SKILL.md instructions |
| Agent description | Skill frontmatter description |
| Built-in tools | Executable Python scripts in `scripts/` |
| Agent skills (workflows) | Step-by-step workflow instructions with script commands |
| Orchestrator skills | Multi-agent workflow skill |
| MCP servers | Noted as runtime-only (not portable) |
| RAG context | Noted as runtime-only (not portable) |
| Guardrails (global + per-agent) | Input/output rules section with actions and config |

Each agent skill includes a `scripts/` folder with standalone Python scripts that Claude Code can execute directly. Tools from the same source module are grouped into a single script file with a CLI wrapper that accepts `--arg value` arguments.

## Configuration

The `--config` (`-c`) flag points to an `orchid.yml` file:

```yaml
llm:
  model: ollama/llama3.2
agents:
  config_path: agents.yaml
auth:
  dev_bypass: false                # set true to skip OAuth entirely
  identity_resolver_class: myapp.identity.Resolver  # optional
  domain: platform.example.com                       # optional
  cli:
    client_id: my-cli-app
    scopes: openid api
    issuer: https://auth.example.com          # OIDC auto-discovery
    # OR explicit endpoints:
    # authorization_endpoint: https://auth.example.com/oauth2/authorize
    # token_endpoint: https://auth.example.com/oauth2/token
rag:
  vector_backend: null      # no Qdrant needed for basic usage
storage:
  class: orchid_ai.persistence.sqlite.SQLiteChatStorage
  dsn: ~/.orchid/chats.db

# LangGraph checkpointer (optional) — enables persistent graph state,
# required for Human-in-the-Loop tool approval
checkpointer:
  type: sqlite                   # memory | sqlite | postgres | dotted.Class
  dsn: ~/.orchid/checkpoints.db
```

### Defaults

| Parameter | Default | Env Override |
|-----------|---------|-------------|
| LLM model | `ollama/llama3.2` | `LITELLM_MODEL` |
| Vector backend | `qdrant` | `VECTOR_BACKEND` |
| Storage class | `orchid_ai.persistence.sqlite.SQLiteChatStorage` | `CHAT_STORAGE_CLASS` |
| Storage DSN | `~/.orchid/chats.db` | `CHAT_DB_DSN` |
| Checkpointer | disabled | `CHECKPOINTER_TYPE` / `CHECKPOINTER_DSN` |
| Token storage | `~/.orchid/tokens.json` | — |

Chat data is stored in SQLite at `~/.orchid/chats.db` by default. OAuth tokens are stored at `~/.orchid/tokens.json` with owner-only permissions (`0o600`). Both directories are created automatically on first use.

### Checkpointing

The CLI supports LangGraph checkpointers for persistent graph state. This is **required** when any agent uses Human-in-the-Loop (`requires_approval: true` on tools).

```yaml
# In orchid.yml
checkpointer:
  type: sqlite              # "memory" | "sqlite" | "postgres" | dotted.Class.Path
  dsn: ~/.orchid/checkpoints.db
```

Install checkpointer extras as needed:

```bash
pip install orchid-ai[checkpoint-sqlite]      # SQLite backend
pip install orchid-ai[checkpoint-postgres]    # PostgreSQL backend
pip install orchid-ai[all-checkpoints]        # Both
```

## Authentication

The CLI supports **OAuth 2.0 Authorization Code + PKCE** for authenticating with external services. This is a generic, provider-agnostic flow that works with any standard OAuth 2.0 / OIDC provider (Okta, Auth0, Keycloak, etc.).

### How It Works

1. `orchid auth login` opens the system browser to the provider's authorization page
2. User authenticates and consents
3. Provider redirects to a temporary `localhost` callback server
4. CLI exchanges the authorization code for access + refresh tokens (with PKCE verification)
5. Tokens are stored at `~/.orchid/tokens.json`
6. All subsequent `orchid chat` commands use the stored token automatically

### OIDC Discovery

When `issuer` is set in the config, the CLI fetches `{issuer}/.well-known/openid-configuration` to auto-discover `authorization_endpoint` and `token_endpoint`. This is the recommended approach -- you only need the issuer URL.

### Token Refresh

When the access token expires and a refresh token is available, the CLI refreshes automatically before sending the request. If refresh fails, you'll be prompted to run `orchid auth login` again.

### Identity Resolution

When `identity_resolver_class` is configured, the CLI calls the resolver after login to populate `tenant_key` and `user_id` from the OAuth token. These identity fields are cached in the token file so subsequent commands don't need the resolver. See the [orchid IdentityResolver ABC](../orchid/orchid_ai/core/identity.py) for the interface.

### Dev Fallback

When `auth.dev_bypass: true` or `auth.cli` is absent, the CLI uses a dummy token (`cli-token`, tenant=`cli`, user=`cli-user`). This is fully backward compatible -- existing configs without OAuth continue to work unchanged.

## Prerequisites

- Python 3.11+
- Ollama running locally (for local LLM models): `ollama pull llama3.2`

## Extending the CLI (plugins)

Consumer packages can register **custom CLI subcommands** via Python entry points — no fork or patch required. Declare a `typer.Typer` instance and expose it in `pyproject.toml`:

```toml
# In your consumer package's pyproject.toml
[project.entry-points."orchid_cli.commands"]
mycommand = "mypackage.cli:app"
```

```python
# mypackage/cli.py
import typer
app = typer.Typer(help="My custom commands")

@app.command()
def greet(name: str):
    """Greet someone."""
    typer.echo(f"Hello {name}!")
```

After `pip install mypackage`, the command is available as `orchid mycommand greet Alice`. Plugins load automatically at startup; failed plugins log a warning but do not block the CLI.

## Architecture

```
orchid_cli/
  main.py          Typer entry point — registers built-in + plugin subcommands
  bootstrap.py     Shared startup: load config, build graph, init storage,
                   wire checkpointer (optional)
  auth/            OAuth 2.0 authentication (self-contained)
    config.py      Provider settings from orchid.yml
    oidc.py        Shared OIDC discovery utility
    flow.py        Authorization Code + PKCE flow (browser, localhost callback)
    token_store.py Secure token persistence (~/.orchid/tokens.json)
    middleware.py  Token refresh + AuthContext builder
    pkce.py        PKCE code verifier/challenge helpers
  commands/
    auth.py        login, logout, status subcommands
    chat.py        Full CRUD + messaging + interactive mode (slash-command
                   dispatch table)
    config.py      Validate agents.yaml
    mcp.py         Per-server MCP OAuth: status, authorize, revoke
                   (shares PKCE flow via oidc.py utility)
    index.py       On-demand RAG seeding: seed, file, dir, text, json-file
    skill.py       Generate Claude Code skills from agents.yaml
```

The CLI is a thin layer that calls `orchid` SDK functions and displays results via Rich. The `auth/` subpackage is fully self-contained — no OAuth logic leaks into chat commands or bootstrap. Interactive-mode slash commands use a dispatch table (`_SLASH_COMMANDS` in `chat.py`) so new slash commands can be added with a single handler function.

## Development

```bash
pip install -e ../orchid -e ".[dev]"
orchid config validate ../examples/basketball/agents.yaml
```

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -x
ruff check orchid_cli/
```

## License

MIT -- see [LICENSE](LICENSE).
