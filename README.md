<p align="center">
  <img src="icon.svg" alt="Orchid" width="80" />
</p>

<h1 align="center">Orchid CLI</h1>

Command-line interface for the [Orchid](https://github.com/gadz82/orchid) multi-agent AI framework.

Provides terminal access to all chat operations, configuration validation, RAG indexing, MCP server authorisation, and Claude Code skill generation. Mirrors the full functionality of [orchid-api](https://github.com/gadz82/orchid-api) but runs locally with no server, Docker, or external database required (defaults to SQLite).

## Why use the CLI

- **Embedded workflows** — the CLI runs the same Orchid runtime as the API but in-process. Useful for batch jobs, scripted pipelines, and offline environments.
- **Identical config surface** — point at any `orchid.yml` / `agents.yaml` pair (basketball, restaurant, helpdesk, your own) and the CLI behaves the way orchid-api does, minus the HTTP layer.
- **Zero-infrastructure RAG** — defaults to ChromaDB (via `orchid-rag-chroma` plugin) for on-disk vector storage. Add Qdrant / Neo4j only when you need them.
- **No infrastructure required** — defaults to SQLite chat storage. Add Postgres via `orchid-storage-postgres` only when you need it.
- **Plugin extensible** — register custom subcommands via Python entry points without forking.
- **Skill export** — turn an `agents.yaml` into a set of Claude Code skill folders so the same agents are usable from `claude` directly.

## Installation

```bash
pip install orchid-ai orchid-cli
```

`orchid-cli` bundles `orchid-rag-chroma` as a dependency for zero-infrastructure RAG (ChromaDB on-disk). Install additional plugins for other backends:

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

## Common workflows

```bash
# 1) Try a built-in example with no setup
# Clone examples repo first: git clone https://github.com/gadz82/orchid-examples
orchid chat interactive -c orchid-examples/basketball/orchid.yml

# 2) Validate every example (CI-friendly)
for f in orchid-examples/**/agents.yaml orchid-examples/**/config/agents.yaml; do
    orchid config validate "$f"
done

# 3) Pre-seed RAG with internal documentation
orchid index dir ./docs/internal -n knowledge_base -c orchid.yml --pattern '*.md'

# 4) Export agents as Claude Code skills for ad-hoc usage
orchid skill generate orchid-examples/restaurant/config/agents.yaml -o ~/.claude/skills

# 5) Drive a non-interactive chat from a shell script
chat_id=$(orchid chat create -c orchid.yml -t "batch-$(date +%s)" --json | jq -r .id)
for q in "$@"; do
    orchid chat send "$chat_id" "$q" -c orchid.yml
done
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

Chat IDs support **prefix matching** — type the first few characters of the UUID.

### Messaging

```bash
# Send a single message and print the response
orchid chat send <chat_id> "What is LangGraph?" -c orchid.yml

# Override the LLM model
orchid chat send <chat_id> "Explain RAG" -c orchid.yml -m ollama/llama3.2
```

The CLI honours every framework feature exposed by the YAML config:

- **Mini-agents** — when an agent has `mini_agent.enabled: true`, the CLI streams the same `mini_agent.{decomposed,started,finished,aggregated}` lifecycle markers the frontend renders, surfaced in the terminal as collapsible sections.
- **Parallel tools** — `parallel_tools: true` on an agent activates intra-round parallel dispatch; the CLI doesn't need any special flag.
- **Prompt customisation** — every `prompt_sections` and `transformer_prompts` override declared in YAML applies inside the CLI just like the API.
- **Sliding-window summarization** — `supervisor.history_summary_enabled: true` compresses older history before the LLM call. CLI users see the same effect on long chats.

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

Validation runs the full Pydantic schema, the defaults-merger pass, and any custom validators registered via the `OrchidAgentsConfig` plugin hooks. Errors include the exact field path and the offending value.

### MCP Server Authorization

Manage per-server OAuth for MCP servers that declare `auth.mode: oauth` in `agents.yaml`.

```bash
# Show authorization status for every OAuth-enabled MCP server
orchid mcp status -c orchid.yml

# Revoke the stored token for a server
orchid mcp revoke <server-name> -c orchid.yml
```

Authorization itself runs through the API gateway's OAuth callback — the CLI's job is only to surface status and let the user revoke a stored token.

### RAG Indexing

Index documents into the vector store, **on startup or any time later**:

```bash
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

### Pollen & Bloom (events)

Local-only ops surface that mirrors the [orchid-api events endpoints](https://github.com/gadz82/orchid-api#pollen--bloom--events-surface). Every command runs in-process against the same dispatcher / queue / store the API would use, so the `events:` block in `agents.yaml` must be `enabled: true` and properly configured before these commands work. **Naming reminder:** *Pollen* is the signal substrate (ingest + queue). *Bloom* is the execution layer (one `JobRun` row per attempt of a matched trigger).

```bash
# Emit a signal through the local dispatcher
orchid signals emit support.ticket.created \
    --payload '{"priority":"high","subject":"VPN down","requester":{"id":"u-42"}}' \
    --source webhook:support-system \
    --tenant acme \
    --correlation-id ticket-2026-0501 \
    -c orchid.yml

# Inspect signals
orchid signals list -c orchid.yml --type support.ticket.created --since 1h --limit 20
orchid signals show <signal_id> -c orchid.yml

# Inspect Bloom runs
orchid runs list -c orchid.yml --status failed --since 1d
orchid runs show <run_id> -c orchid.yml
orchid runs retry <run_id> -c orchid.yml         # re-enqueue → fresh attempt_number
orchid runs cancel <run_id> -c orchid.yml        # best-effort flag

# Inspect declared triggers + per-trigger run history
orchid jobs list -c orchid.yml
orchid jobs runs <trigger_id> -c orchid.yml --status succeeded

# Schedules — list + toggle (cron / interval rows declared in events.schedules[])
orchid schedules list -c orchid.yml
orchid schedules show <schedule_id> -c orchid.yml
orchid schedules enable <schedule_id> -c orchid.yml
orchid schedules disable <schedule_id> -c orchid.yml
```

**`signals emit` flags:**

| Flag | Purpose | Default |
|------|---------|---------|
| `<type>` (positional) | Signal type — must match an active trigger's `on.signal` | required |
| `--payload` / `-p` | JSON body. Triggers' `when:` JMESPath expressions run against this | `{}` |
| `--source` / `-s` | Logical signal source — used together with `--dedupe-key` for the `UNIQUE (source, dedupe_key)` constraint | `cli:orchid` |
| `--tenant` / `-t` | Tenant key written into the envelope | `default` |
| `--user` / `-u` | Originating user id — required by triggers using `act_as_user` / `addressed_to_user` identity | — |
| `--dedupe-key` / `-k` | Idempotency key. A duplicate emit returns the existing `signal_id` with `deduplicated: true` | — |
| `--correlation-id` | Correlation id linking related signals | — |
| `--identity` | JSON identity claim override (rare — defaults to the CLI's `OrchidAuthContext`) | — |

The CLI honours the same idempotency, visibility filtering, and audit trail that orchid-api enforces — emitting from the CLI on a Postgres-backed config is exactly the same as POSTing a webhook to `orchid-api`. Use it for: smoke-testing a new trigger before wiring an upstream producer; replaying a single signal during incident triage; bulk-emitting a small fixture set in dev.

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

The skill generator pulls parameter metadata from the YAML `tools:` block when present, and falls back to Python signature introspection when omitted.

### Project Scaffolding (generate-flower)

Interactive wizard that guides you through creating a complete Orchid project skeleton — `orchid.yml`, `agents.yaml`, and Python scaffold files — packaged as a zip or written directly to a directory.

```bash
# Start the interactive wizard
orchid generate-flower

# Write directly to a directory (no zip)
orchid generate-flower --no-zip --output ./my-project

# With AI assistance (explains options, suggests values)
orchid generate-flower --ai --ai-model openai/gpt-4o

# Reproduce a previous project from a seed file
orchid generate-flower --from-seed answers.json

# Verbose mode (shows all questions, even with defaults)
orchid generate-flower --verbose
```

**Wizard phases:**

| Phase | What it configures |
|---|---|
| Project Identity | Name, description, output directory |
| Infrastructure | LLM provider/model, auth mode, vector backend, embedding model, storage, uploads, checkpointer, tracing |
| Supervisor | Assistant name, routing model, history limits, summarization |
| Agents | Name, description, system prompt, custom class, RAG, MCP servers, tools, skills, guardrails, mini-agents, children |
| Global Tools | Tool name, handler, parameters, RAG injection, approval |
| Cross-Agent Skills | Skill name, description, agent/instruction steps |
| Global Guardrails | Input rules (prompt injection, content safety, max length, topic restriction), output rules (PII detection, content safety) |
| Events (Pollen + Bloom) | Store/queue/scheduler backends, producers, processors, schedules, triggers |
| MCP Gateway | Tool title/description overrides, prompt templates |

**Generated structure:**

```
my_project/
├── __init__.py
├── orchid.yml
├── agents.yaml
├── README.md
├── agents/
│   ├── __init__.py
│   └── {custom_agent}.py
├── tools/
│   ├── __init__.py
│   └── {tool_name}.py
├── identity.py              # if custom auth selected
├── hooks/
│   ├── __init__.py
│   └── {hook_name}.py
├── storage/
│   ├── __init__.py
│   └── {storage_name}.py
└── tests/
    ├── __init__.py
    └── test_agents.py
```

All generated YAML is schema-validated before output. All generated Python files include `from __future__ import annotations` and follow project SOLID conventions. The review phase lets you inspect and edit any answer before finalizing.

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
  class: orchid_ai.persistence.sqlite.OrchidSQLiteChatStorage
  dsn: ~/.orchid/chats.db

# Startup hook (e.g. seeds RAG, registers custom strategies / tools)
startup:
  hook: examples.travel-agency.hooks.startup.bootstrap_travel

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
| Vector backend | `chroma` (via orchid-rag-chroma plugin) | `VECTOR_BACKEND` |
| ChromaDB path | `~/.orchid/chroma` | `CHROMA_PATH` |
| Storage class | `orchid_ai.persistence.sqlite.OrchidSQLiteChatStorage` | `CHAT_STORAGE_CLASS` |
| Storage DSN | `~/.orchid/chats.db` | `CHAT_DB_DSN` |
| Checkpointer | disabled | `CHECKPOINTER_TYPE` / `CHECKPOINTER_DSN` |
| Token storage | `~/.orchid/tokens.json` | — |

Chat data is stored in SQLite at `~/.orchid/chats.db` by default. OAuth tokens are stored at `~/.orchid/tokens.json` with owner-only permissions (`0o600`). Both directories are created automatically on first use.

### Checkpointing

The CLI supports LangGraph checkpointers for persistent graph state. This is **required** when any agent uses Human-in-the-Loop (`requires_approval: true` on tools) or relies on resume-after-interrupt flows.

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

1. `orchid auth login` opens the system browser to the provider's authorization page.
2. User authenticates and consents.
3. Provider redirects to a temporary `localhost` callback server.
4. CLI exchanges the authorization code for access + refresh tokens (with PKCE verification).
5. Tokens are stored at `~/.orchid/tokens.json` with `0o600` permissions.
6. All subsequent `orchid chat` commands use the stored token automatically.

### OIDC Discovery

When `issuer` is set in the config, the CLI fetches `{issuer}/.well-known/openid-configuration` to auto-discover `authorization_endpoint` and `token_endpoint`. This is the recommended approach — you only need the issuer URL.

### Token Refresh

When the access token expires and a refresh token is available, the CLI refreshes automatically before sending the request. If refresh fails, you'll be prompted to run `orchid auth login` again.

### Identity Resolution

When `identity_resolver_class` is configured, the CLI calls the resolver after login to populate `tenant_key` and `user_id` from the OAuth token. These identity fields are cached in the token file so subsequent commands don't need the resolver. See the [`OrchidIdentityResolver` ABC](https://github.com/gadz82/orchid/blob/main/orchid_ai/core/identity.py) for the interface.

> **Note:** the CLI is an **independent OAuth client** — it runs its own
> authorization-code + PKCE dance against the upstream IdP and calls the
> identity resolver locally. It does NOT use the
> centralised `/auth/exchange-code` / `/auth/resolve-identity` /
> `/auth/refresh-token` endpoints that the MCP gateway uses.
> The CLI ships with the upstream secret `client_id` baked into its config
> because it's a desktop app, not a network service.

### Dev Fallback

When `auth.dev_bypass: true` or `auth.cli` is absent, the CLI uses a dummy token (`cli-token`, tenant=`cli`, user=`cli-user`). This is fully backward compatible — existing configs without OAuth continue to work unchanged.

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
                   wire checkpointer (optional), invoke startup hook
  auth/            OAuth 2.0 authentication (self-contained)
    config.py      Provider settings from orchid.yml
    oidc.py        Shared OIDC discovery utility
    flow.py        Authorization Code + PKCE flow (browser, localhost callback)
    token_store.py Secure token persistence (~/.orchid/tokens.json)
    middleware.py  Token refresh + OrchidAuthContext builder
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
    signals.py     Pollen — emit / list / show signals through the local dispatcher
    runs.py        Bloom — list / show / retry / cancel JobRun rows
    jobs.py        Trigger registry inspection + per-trigger runs
    schedules.py   Schedule list / show / enable / disable
```

`bootstrap.py` mirrors the orchid-api lifespan: load and validate config, build the LangGraph runtime, initialise the storage backend, wire the checkpointer, fire the startup hook (if any), and — when the YAML carries an `events:` block with `enabled: true` — boot the same `start_events()` helper that orchid-api uses (resolves dotted paths for store / queue / scheduler / processors / producers, builds the trigger registry, runs the boot-time `act_as_user` mint probe). The chat commands then attach an `OrchidAuthContext` per call and enter the supervisor; the `signals` / `runs` / `jobs` / `schedules` commands talk to the same dispatcher + stores that the API exposes — the only difference is the absence of the FastAPI shell.

## Embedded mode (using the SDK directly)

For applications that need Orchid as a library rather than a CLI:

```python
from orchid_ai import Orchid, OrchidRuntime
from orchid_ai.config.loader import load_config

config = load_config("orchid.yml")
runtime = OrchidRuntime.from_config(config)
async with runtime:
    answer = await runtime.ask(
        "Hello!",
        tenant_id="default",
        user_id="me",
        chat_id="chat-1",
    )
    print(answer.text)
```

The CLI uses these primitives internally; embedded users get the same behaviour without the Typer shell. See [orchid-examples/embedded-python](https://github.com/gadz82/orchid-examples/tree/main/embedded-python) for end-to-end patterns.

## Troubleshooting

- **`Cannot resolve chat storage class '…'`** — the dotted import path in `storage.class` failed to import. Confirm the package is installed and the module path is reachable from `PYTHONPATH`.
- **`No module named 'aiosqlite'`** — install the SQLite extra: `pip install orchid-ai[checkpoint-sqlite]`.
- **OAuth `redirect_uri_mismatch`** — register `http://localhost:<port>/callback` (the port the CLI prints on `auth login`) with your IdP. Some IdPs accept the loopback wildcard `http://127.0.0.1`; others require the literal port.
- **Tokens stored but `auth status` shows expired** — refresh failed. Inspect `~/.orchid/tokens.json` (chmod 600) and re-run `orchid auth login`.
- **Slow startup with custom LLM provider** — `bootstrap.py` initialises the chat model lazily, but startup hooks run synchronously. Move heavy work behind `if reader and reader.supports_writes:` guards inside the hook.
- **`No agents loaded`** — likely missing `agents.config_path` in `orchid.yml`. Inline-config users should switch to `agents:` (see [orchid-examples/embedded-python/06_inline_config.py](https://github.com/gadz82/orchid-examples/blob/main/embedded-python/06_inline_config.py)).
- **`signals` / `runs` / `jobs` / `schedules` commands fail with `events not enabled`** — the `events:` block in `agents.yaml` is missing or `enabled: false`. Set `events.enabled: true` and supply at minimum `events.store`, `events.queue`, and one entry under `events.processors` (see the [orchid `events:` reference](https://github.com/gadz82/orchid#events-pollen--bloom--optional-opt-in)).
- **`MintingProbeUnsupportedError` at startup** — a trigger declares `identity.mode: act_as_user` but the configured `OrchidIdentityResolver` does not implement `mint_for_user`. Either switch the trigger to a service-account identity or wire a resolver that mints.

## Development

```bash
pip install -e orchid-ai -e orchid-cli
orchid config validate orchid-examples/basketball/agents.yaml
```

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -x
ruff check orchid_cli/
```

## Related Projects

- **[orchid-examples](https://github.com/gadz82/orchid-examples)** — Example configurations, custom agents, and integration patterns

## License

MIT — see [LICENSE](LICENSE).
