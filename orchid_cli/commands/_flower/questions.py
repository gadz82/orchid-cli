from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class QuestionType(str, Enum):
    SELECT = "select"
    TEXT = "text"
    NUMBER = "number"
    BOOL = "bool"
    MULTI_SELECT = "multi_select"
    PATH = "path"
    LONG_TEXT = "long_text"


@dataclass
class Question:
    key: str
    prompt: str
    type: QuestionType
    choices: list[str] | None = None
    default: Any | None = None
    validator: Callable[[str], tuple[bool, str]] | None = None
    condition: Callable[[dict[str, Any]], bool] | None = None
    help_text: str | None = None


@dataclass
class Phase:
    name: str
    questions: list[Question]
    condition: Callable[[dict[str, Any]], bool] | None = None


LLM_PROVIDERS = ["ollama", "openai", "anthropic", "gemini", "groq"]
VECTOR_BACKENDS = ["qdrant", "null", "chroma"]
STORAGE_BACKENDS = ["sqlite", "postgresql", "custom"]
AUTH_MODES = ["dev_bypass", "custom", "oauth"]
CHECKPOINTERS = ["memory", "sqlite", "postgres", "none"]
MCP_AUTH_MODES = ["none", "passthrough", "oauth"]
TOOL_CALL_STRATEGIES = ["all", "sequential", "llm_decides"]
INGESTION_STRATEGIES = ["recursive", "semantic", "hierarchical", "headered"]
RETRIEVAL_STRATEGIES = ["simple", "multi_query", "hyde", "hybrid", "graph_rag"]
AGENT_TYPES = ["GenericAgent", "custom"]
INPUT_GUARDRAIL_TYPES = ["prompt_injection", "content_safety", "max_length", "topic_restriction"]
OUTPUT_GUARDRAIL_TYPES = ["pii_detection", "content_safety"]
GUARDRAIL_ACTIONS = ["block", "warn", "redact"]


def _embedding_default(answers: dict[str, Any]) -> str:
    provider = answers.get("llm.provider", "ollama")
    defaults = {
        "ollama": "ollama/nomic-embed-text",
        "openai": "text-embedding-3-small",
        "anthropic": "text-embedding-3-small",
        "gemini": "gemini/gemini-embedding-001",
        "groq": "text-embedding-3-small",
    }
    return defaults.get(provider, "ollama/nomic-embed-text")


def _skip_if_null_vector(answers: dict[str, Any]) -> bool:
    val = answers.get("infrastructure", {}).get(
        "vector_backend", answers.get("infrastructure.vector_backend", "qdrant")
    )
    return val == "null"


def _skip_if_null_vector_url(answers: dict[str, Any]) -> bool:
    val = answers.get("infrastructure", {}).get(
        "vector_backend", answers.get("infrastructure.vector_backend", "qdrant")
    )
    return val not in ("qdrant", "chroma")


def _skip_if_sqlite_storage(answers: dict[str, Any]) -> bool:
    return answers.get("infrastructure.storage_backend", "sqlite") != "custom"


def _skip_if_dev_bypass(answers: dict[str, Any]) -> bool:
    return answers.get("infrastructure.auth_mode", "dev_bypass") != "custom"


def _skip_if_no_tracing(answers: dict[str, Any]) -> bool:
    return answers.get("infrastructure.langsmith_tracing", False) is False


def _skip_if_no_startup_hook(answers: dict[str, Any]) -> bool:
    return answers.get("infrastructure.startup_hook_path", "") == ""


def _summary_enabled(answers: dict[str, Any]) -> bool:
    sup = answers.get("supervisor", {})
    return sup.get("history_summary_enabled", False) is True


def _memory_strategy_enabled(answers: dict[str, Any]) -> bool:
    sup = answers.get("supervisor", {})
    memory = sup.get("memory", {})
    return memory.get("strategy", "none") != "none"


PHASE_0_IDENTITY = Phase(
    name="Project Identity",
    questions=[
        Question(
            key="project.name",
            prompt="Project name (used as Python package name)",
            type=QuestionType.TEXT,
            default="my_orchid_project",
            help_text="Lowercase, no spaces, valid Python identifier",
        ),
        Question(
            key="project.description",
            prompt="Project description (one-liner for README)",
            type=QuestionType.TEXT,
            default="An Orchid AI project",
        ),
        Question(
            key="project.output_dir",
            prompt="Output directory for the generated project",
            type=QuestionType.PATH,
            default=".",
        ),
    ],
)

PHASE_1_INFRASTRUCTURE = Phase(
    name="Infrastructure",
    questions=[
        Question(
            key="infrastructure.llm_provider",
            prompt="Which LLM provider?",
            type=QuestionType.SELECT,
            choices=LLM_PROVIDERS,
            default="ollama",
        ),
        Question(
            key="infrastructure.llm_model",
            prompt="LLM model (provider/model format)",
            type=QuestionType.TEXT,
            default="ollama/llama3.2",
            help_text="e.g., openai/gpt-4o, anthropic/claude-sonnet-4-20250514, gemini/gemini-2.5-flash",
        ),
        Question(
            key="infrastructure.ollama_api_base",
            prompt="Ollama API base URL (if using ollama)",
            type=QuestionType.TEXT,
            default="http://localhost:11434",
            condition=lambda a: a.get("infrastructure.llm_provider") == "ollama",
        ),
        Question(
            key="infrastructure.auth_mode",
            prompt="Authentication mode",
            type=QuestionType.SELECT,
            choices=AUTH_MODES,
            default="dev_bypass",
            help_text="dev_bypass: skip auth for local dev; custom: your own identity resolver; oauth: full OAuth2 flow",
        ),
        Question(
            key="infrastructure.identity_resolver_class",
            prompt="Identity resolver dotted path (e.g., myproject.identity.MyResolver)",
            type=QuestionType.TEXT,
            default="",
            condition=_skip_if_dev_bypass,
        ),
        Question(
            key="infrastructure.vector_backend",
            prompt="Vector backend for RAG",
            type=QuestionType.SELECT,
            choices=VECTOR_BACKENDS,
            default="qdrant",
            help_text="qdrant: full-featured vector DB; chroma: lightweight local; null: disable RAG",
        ),
        Question(
            key="infrastructure.qdrant_url",
            prompt="Qdrant URL",
            type=QuestionType.TEXT,
            default="http://localhost:6333",
            condition=lambda a: a.get("infrastructure.vector_backend") == "qdrant",
        ),
        Question(
            key="infrastructure.chroma_path",
            prompt="ChromaDB path",
            type=QuestionType.PATH,
            default="~/.orchid/chroma",
            condition=lambda a: a.get("infrastructure.vector_backend") == "chroma",
        ),
        Question(
            key="infrastructure.embedding_model",
            prompt="Embedding model",
            type=QuestionType.TEXT,
            default=_embedding_default,
            condition=_skip_if_null_vector,
            help_text="Must match your vector backend's expected dimensions",
        ),
        Question(
            key="infrastructure.storage_backend",
            prompt="Chat storage backend",
            type=QuestionType.SELECT,
            choices=STORAGE_BACKENDS,
            default="sqlite",
        ),
        Question(
            key="infrastructure.storage_class",
            prompt="Storage class dotted path",
            type=QuestionType.TEXT,
            default="",
            condition=_skip_if_sqlite_storage,
        ),
        Question(
            key="infrastructure.storage_dsn",
            prompt="Storage DSN (database path or connection string)",
            type=QuestionType.TEXT,
            default="~/.orchid/chats.db",
        ),
        Question(
            key="infrastructure.vision_model",
            prompt="Vision model for document uploads",
            type=QuestionType.TEXT,
            default="ollama/minicpm-v",
        ),
        Question(
            key="infrastructure.upload_namespace",
            prompt="Upload namespace for RAG",
            type=QuestionType.TEXT,
            default="uploads",
        ),
        Question(
            key="infrastructure.upload_max_size_mb",
            prompt="Max upload size (MB)",
            type=QuestionType.NUMBER,
            default=20,
        ),
        Question(
            key="infrastructure.chunk_size",
            prompt="Document chunk size (characters)",
            type=QuestionType.NUMBER,
            default=1000,
        ),
        Question(
            key="infrastructure.chunk_overlap",
            prompt="Chunk overlap (characters)",
            type=QuestionType.NUMBER,
            default=200,
        ),
        Question(
            key="infrastructure.checkpointer",
            prompt="LangGraph checkpointer",
            type=QuestionType.SELECT,
            choices=CHECKPOINTERS,
            default="memory",
        ),
        Question(
            key="infrastructure.langsmith_tracing",
            prompt="Enable LangSmith tracing?",
            type=QuestionType.BOOL,
            default=False,
        ),
        Question(
            key="infrastructure.api_base_url",
            prompt="API base URL prefix",
            type=QuestionType.TEXT,
            default="",
            help_text="Leave empty for default (/api/v1)",
        ),
        Question(
            key="infrastructure.startup_hook_path",
            prompt="Startup hook dotted path (e.g., myproject.hooks.on_startup)",
            type=QuestionType.TEXT,
            default="",
            help_text="Leave empty for no startup hook",
        ),
    ],
)

PHASE_2_SUPERVISOR = Phase(
    name="Supervisor Configuration",
    questions=[
        Question(
            key="supervisor.assistant_name",
            prompt="Assistant display name",
            type=QuestionType.TEXT,
            default="Orchid Assistant",
        ),
        Question(
            key="supervisor.routing_model",
            prompt="Routing model (leave empty to use default LLM)",
            type=QuestionType.TEXT,
            default="",
            help_text="Use a cheaper/faster model for routing if desired",
        ),
        Question(
            key="supervisor.fallback_model",
            prompt="Fallback LLM model for supervisor (leave empty to use default)",
            type=QuestionType.TEXT,
            default="",
            help_text="Used when the primary model fails",
        ),
        Question(
            key="supervisor.history_max_turns",
            prompt="Max conversation history turns for supervisor",
            type=QuestionType.NUMBER,
            default=20,
        ),
        Question(
            key="supervisor.history_max_chars",
            prompt="Max conversation history characters for supervisor",
            type=QuestionType.NUMBER,
            default=1000,
        ),
        Question(
            key="supervisor.history_summary_enabled",
            prompt="Enable sliding-window summarization for long histories?",
            type=QuestionType.BOOL,
            default=True,
        ),
        Question(
            key="supervisor.history_summary_recent_turns",
            prompt="Number of recent turns to keep verbatim (when summarization enabled)",
            type=QuestionType.NUMBER,
            default=10,
            condition=_summary_enabled,
        ),
        Question(
            key="supervisor.history_summary_model",
            prompt="Summarization model (leave empty to use default)",
            type=QuestionType.TEXT,
            default="",
            help_text="Leave empty to reuse the supervisor model",
            condition=_summary_enabled,
        ),
        # ── Conversation memory strategy ──
        Question(
            key="supervisor.memory.strategy",
            prompt="Conversation memory strategy",
            type=QuestionType.SELECT,
            choices=["none", "running_summary", "rag_augmented"],
            default="none",
            help_text="none: no cross-session memory; running_summary: incremental summarization; rag_augmented: vector-backed memory retrieval",
        ),
        Question(
            key="supervisor.memory.summary_recent_turns",
            prompt="Recent turns to keep verbatim in memory summaries",
            type=QuestionType.NUMBER,
            default=10,
            condition=_memory_strategy_enabled,
        ),
        Question(
            key="supervisor.memory.truncation_strategy",
            prompt="Truncation strategy for long messages",
            type=QuestionType.SELECT,
            choices=["hard", "middle", "llm", "semantic"],
            default="hard",
            help_text="hard: cut at limit (fast); middle: keep start+end; llm: LLM-compress (costly); semantic: RAG-based",
        ),
        Question(
            key="supervisor.memory.truncation_max_chars",
            prompt="Max characters per message before truncation",
            type=QuestionType.NUMBER,
            default=1000,
        ),
        Question(
            key="supervisor.streaming_enabled",
            prompt="Enable SSE streaming for responses?",
            type=QuestionType.BOOL,
            default=True,
        ),
        Question(
            key="supervisor.skip_synthesis_when_single_agent",
            prompt="Skip supervisor synthesis when only one agent responds?",
            type=QuestionType.BOOL,
            default=True,
            help_text="Saves LLM cost when a single agent generates the full response",
        ),
    ],
)

PHASE_3_AGENT_LOOP = Phase(
    name="Agent Definition (repeat until done)",
    questions=[
        Question(
            key="_agent.add_more",
            prompt="Add another agent?",
            type=QuestionType.BOOL,
            default=True,
        ),
    ],
)

PHASE_4_GLOBAL_TOOLS = Phase(
    name="Global Tools Definition (repeat until done)",
    questions=[
        Question(
            key="_tools.add_more",
            prompt="Add another global tool?",
            type=QuestionType.BOOL,
            default=False,
        ),
    ],
)

PHASE_5_SKILLS = Phase(
    name="Cross-Agent Skills (repeat until done)",
    questions=[
        Question(
            key="_skills.add_more",
            prompt="Add another cross-agent skill?",
            type=QuestionType.BOOL,
            default=False,
        ),
    ],
)

PHASE_6_GUARDRAILS = Phase(
    name="Global Guardrails",
    questions=[
        Question(
            key="_guardrails.input_enabled",
            prompt="Configure input guardrails?",
            type=QuestionType.BOOL,
            default=True,
        ),
        Question(
            key="_guardrails.output_enabled",
            prompt="Configure output guardrails?",
            type=QuestionType.BOOL,
            default=True,
        ),
    ],
)

PHASE_7_EVENTS = Phase(
    name="Events (Pollen + Bloom)",
    questions=[
        Question(
            key="events.enabled",
            prompt="Enable events (Pollen + Bloom)?",
            type=QuestionType.BOOL,
            default=False,
        ),
    ],
)

PHASE_8_MCP_GATEWAY = Phase(
    name="MCP Gateway Customization",
    questions=[
        Question(
            key="_mcp_gateway.configure",
            prompt="Configure MCP gateway tool title/description overrides?",
            type=QuestionType.BOOL,
            default=False,
        ),
    ],
)

ALL_PHASES = [
    PHASE_0_IDENTITY,
    PHASE_1_INFRASTRUCTURE,
    PHASE_2_SUPERVISOR,
    PHASE_3_AGENT_LOOP,
    PHASE_4_GLOBAL_TOOLS,
    PHASE_5_SKILLS,
    PHASE_6_GUARDRAILS,
    PHASE_7_EVENTS,
    PHASE_8_MCP_GATEWAY,
]
