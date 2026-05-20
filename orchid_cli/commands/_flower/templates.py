from __future__ import annotations

ORCHID_YML_TEMPLATE = """# orchid.yml — {project_name}
# {project_description}

agents:
  config_path: agents.yaml

llm:
  model: {llm_model}
{ollama_api_base_line}

auth:
  dev_bypass: {auth_dev_bypass}
{identity_resolver_line}

rag:
  vector_backend: {vector_backend}
{qdrant_url_line}{chroma_path_line}{embedding_model_line}

upload:
  vision_model: {vision_model}
  namespace: {upload_namespace}
  max_size_mb: {upload_max_size_mb}
  chunk_size: {chunk_size}
  chunk_overlap: {chunk_overlap}

storage:
  class: {storage_class}
  dsn: {storage_dsn}

checkpointer: {checkpointer}

tracing:
  langsmith_tracing: {langsmith_tracing}
""".lstrip()


AGENTS_YAML_TEMPLATE = """version: "1"

defaults:
  llm:
    model: "{defaults_llm_model}"
    temperature: {defaults_llm_temperature}
  rag:
    enabled: {defaults_rag_enabled}

{guardrails_section}
{tools_section}
{skills_section}
agents:
{agents_section}

{mcp_gateway_section}
{events_section}
""".lstrip()


AGENT_PY_TEMPLATE = """from __future__ import annotations

from orchid_ai.core.agent import OrchidAgent
from orchid_ai.core.state import OrchidAgentState, OrchidAuthContext


class {class_name}(OrchidAgent):
    def __init__(self, name: str, **kwargs) -> None:
        super().__init__(name=name, **kwargs)

    async def run(
        self,
        state: OrchidAgentState,
        auth_context: OrchidAuthContext,
    ) -> OrchidAgentState:
        user_query = self.extract_user_query(state)
        context = self.fetch_rag_context(user_query, auth_context)
        state["context"] = context
        return state
""".lstrip()


TOOL_PY_TEMPLATE = """from __future__ import annotations

from typing import Any


async def {handler_name}(
    query: str,
    context: dict[str, Any] | None = None,
    **kwargs: Any,
) -> str:
    \"\"\"{description}\"\"\"
    raise NotImplementedError("Implement this tool handler")
""".lstrip()


IDENTITY_PY_TEMPLATE = """from __future__ import annotations

from orchid_ai.core.identity import OrchidIdentityResolver
from orchid_ai.core.state import OrchidAuthContext


class {class_name}(OrchidIdentityResolver):
    async def resolve(self, bearer_token: str) -> OrchidAuthContext:
        raise NotImplementedError("Implement identity resolution logic")
""".lstrip()


HOOK_PY_TEMPLATE = """from __future__ import annotations

from typing import Any


async def {hook_name}(config: dict[str, Any]) -> None:
    \"\"\"Startup hook for {project_name}.\"\"\"
    pass
""".lstrip()


STORAGE_PY_TEMPLATE = """from __future__ import annotations

from orchid_ai.persistence.base import OrchidChatStorage


class {class_name}(OrchidChatStorage):
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
""".lstrip()


INIT_PY_TEMPLATE = '"""{project_name} — {project_description}"""\n'


README_MD_TEMPLATE = """# {project_name}

{project_description}

## Structure

- `orchid.yml` — Infrastructure configuration
- `agents.yaml` — Agent definitions
- `agents/` — Custom agent classes
- `tools/` — Built-in tool handlers
- `hooks/` — Startup hooks
- `storage/` — Custom storage backends

## Running

```bash
pip install -e ../orchid -e ../orchid-api
ORCHID_CONFIG=orchid.yml uvicorn orchid_api.main:app --port 8000
```

Or via CLI:

```bash
pip install -e ../orchid -e ../orchid-cli
orchid chat interactive --config orchid.yml
```
""".lstrip()


TEST_AGENTS_PY_TEMPLATE = """from __future__ import annotations

from pathlib import Path

import yaml

from orchid_ai.config.loader import load_config


def test_agents_yaml_valid() -> None:
    agents_path = Path(__file__).parent.parent / "agents.yaml"
    with open(agents_path) as f:
        data = yaml.safe_load(f)
    assert "agents" in data
    assert "version" in data


def test_config_loads() -> None:
    config_path = Path(__file__).parent.parent / "orchid.yml"
    config = load_config(str(config_path))
    assert len(config.agents) > 0
""".lstrip()


def _build_orchid_yml(answers: dict) -> str:
    ollama_base = answers.get("infrastructure.ollama_api_base", "")
    ollama_line = (
        f"  ollama_api_base: {ollama_base}\n"
        if ollama_base and answers.get("infrastructure.llm_provider") == "ollama"
        else ""
    )

    auth_mode = answers.get("infrastructure.auth_mode", "dev_bypass")
    dev_bypass = "true" if auth_mode == "dev_bypass" else "false"

    identity_line = ""
    if auth_mode == "custom":
        resolver = answers.get("infrastructure.identity_resolver_class", "")
        if resolver:
            identity_line = f"  identity_resolver_class: {resolver}\n"

    vector_backend = answers.get("infrastructure.vector_backend", "qdrant")
    qdrant_url = answers.get("infrastructure.qdrant_url", "")
    qdrant_line = f"  qdrant_url: {qdrant_url}\n" if qdrant_url and vector_backend == "qdrant" else ""

    chroma_path = answers.get("infrastructure.chroma_path", "")
    chroma_line = f"  chroma_path: {chroma_path}\n" if chroma_path and vector_backend == "chroma" else ""

    embedding = answers.get("infrastructure.embedding_model", "ollama/nomic-embed-text")
    if vector_backend == "null":
        embedding_line = ""
    else:
        embedding_line = f"  embedding_model: {embedding}\n"

    storage_backend = answers.get("infrastructure.storage_backend", "sqlite")
    if storage_backend == "custom":
        storage_class = answers.get("infrastructure.storage_class", "")
    elif storage_backend == "postgresql":
        storage_class = "orchid_ai.persistence.postgres.OrchidPostgresChatStorage"
    else:
        storage_class = "orchid_ai.persistence.sqlite.OrchidSQLiteChatStorage"

    storage_dsn = answers.get("infrastructure.storage_dsn", "~/.orchid/chats.db")
    checkpointer = answers.get("infrastructure.checkpointer", "memory")
    langsmith = "true" if answers.get("infrastructure.langsmith_tracing", False) else "false"

    return ORCHID_YML_TEMPLATE.format(
        project_name=answers.get("project.name", "my_orchid_project"),
        project_description=answers.get("project.description", "An Orchid AI project"),
        llm_model=answers.get("infrastructure.llm_model", "ollama/llama3.2"),
        ollama_api_base_line=ollama_line,
        auth_dev_bypass=dev_bypass,
        identity_resolver_line=identity_line,
        vector_backend=vector_backend,
        qdrant_url_line=qdrant_line,
        chroma_path_line=chroma_line,
        embedding_model_line=embedding_line,
        vision_model=answers.get("infrastructure.vision_model", "ollama/minicpm-v"),
        upload_namespace=answers.get("infrastructure.upload_namespace", "uploads"),
        upload_max_size_mb=answers.get("infrastructure.upload_max_size_mb", 20),
        chunk_size=answers.get("infrastructure.chunk_size", 1000),
        chunk_overlap=answers.get("infrastructure.chunk_overlap", 200),
        storage_class=storage_class,
        storage_dsn=storage_dsn,
        checkpointer=checkpointer,
        langsmith_tracing=langsmith,
    )


def _build_agents_yaml(answers: dict) -> str:
    defaults_model = answers.get("infrastructure.llm_model", "ollama/llama3.2")
    defaults_rag = "true" if answers.get("infrastructure.vector_backend", "qdrant") != "null" else "false"

    guardrails = answers.get("_guardrails", {})
    input_rules = guardrails.get("input", [])
    output_rules = guardrails.get("output", [])

    guardrails_section = ""
    if input_rules or output_rules:
        guardrails_section = "guardrails:\n"
        if input_rules:
            guardrails_section += "  input:\n"
            for rule in input_rules:
                guardrails_section += f"    - type: {rule['type']}\n"
                guardrails_section += f"      fail_action: {rule.get('fail_action', 'block')}\n"
                if "config" in rule:
                    guardrails_section += "      config:\n"
                    for k, v in rule["config"].items():
                        if isinstance(v, list):
                            guardrails_section += f"        {k}: [{', '.join(str(x) for x in v)}]\n"
                        else:
                            guardrails_section += f"        {k}: {v}\n"
        if output_rules:
            guardrails_section += "  output:\n"
            for rule in output_rules:
                guardrails_section += f"    - type: {rule['type']}\n"
                guardrails_section += f"      fail_action: {rule.get('fail_action', 'redact')}\n"
                if "config" in rule:
                    guardrails_section += "      config:\n"
                    for k, v in rule["config"].items():
                        if isinstance(v, list):
                            guardrails_section += f"        {k}: [{', '.join(str(x) for x in v)}]\n"
                        else:
                            guardrails_section += f"        {k}: {v}\n"

    tools = answers.get("_tools", [])
    tools_section = ""
    if tools:
        tools_section = "tools:\n"
        for tool in tools:
            tools_section += f"  {tool['name']}:\n"
            tools_section += f'    handler: "{tool.get("handler", "")}"\n'
            tools_section += f'    description: "{tool.get("description", "")}"\n'
            params = tool.get("parameters", {})
            if params:
                tools_section += "    parameters:\n"
                for pname, pconfig in params.items():
                    tools_section += f"      {pname}:\n"
                    tools_section += f"        type: {pconfig.get('type', 'string')}\n"
                    tools_section += f'        description: "{pconfig.get("description", "")}"\n'
                    tools_section += f"        required: {'true' if pconfig.get('required', False) else 'false'}\n"

    skills = answers.get("_skills", [])
    skills_section = ""
    if skills:
        skills_section = "skills:\n"
        for skill in skills:
            skills_section += f"  {skill['name']}:\n"
            skills_section += f'    description: "{skill.get("description", "")}"\n'
            if skill.get("steps"):
                skills_section += "    steps:\n"
                for step in skill["steps"]:
                    skills_section += f"      - agent: {step.get('agent', '')}\n"
                    skills_section += f'        instruction: "{step.get("instruction", "")}"\n'

    agents = answers.get("_agents", [])
    agents_section = ""
    for agent in agents:
        agents_section += f"  {agent['name']}:\n"
        agents_section += "    description: >\n"
        desc = agent.get("description", "")
        for line in desc.split("\n"):
            agents_section += f"      {line}\n"
        agents_section += "\n"
        agents_section += "    prompt: |\n"
        prompt = agent.get("prompt", "")
        for line in prompt.split("\n"):
            agents_section += f"      {line}\n"
        agents_section += "\n"

        if agent.get("agent_type") == "custom" and agent.get("class_path"):
            agents_section += f"    class: {agent['class_path']}\n"

        agent_tools = agent.get("tools", [])
        if agent_tools:
            agents_section += "    tools:\n"
            for t in agent_tools:
                agents_section += f"      - {t}\n"

        mcp_servers = agent.get("mcp_servers", [])
        if mcp_servers:
            agents_section += "    mcp_servers:\n"
            for mcp in mcp_servers:
                agents_section += f"      - name: {mcp.get('name', '')}\n"
                agents_section += "        type: remote\n"
                agents_section += "        transport: streamable_http\n"
                agents_section += f"        url: {mcp.get('url', '')}\n"
                agents_section += "        auth:\n"
                agents_section += f"          mode: {mcp.get('auth_mode', 'none')}\n"
                tools_val = mcp.get("tools", "*")
                if tools_val == "*":
                    agents_section += "        tools: '*'\n"
                else:
                    agents_section += "        tools:\n"
                    for t in tools_val.split(","):
                        agents_section += f"          - {t.strip()}\n"

        rag_enabled = agent.get("rag_enabled", False)
        if not rag_enabled:
            agents_section += "    rag:\n"
            agents_section += "      enabled: false\n"
        else:
            agents_section += "    rag:\n"
            agents_section += "      enabled: true\n"
            agents_section += f"      namespace: {agent.get('rag_namespace', agent['name'])}\n"
            agents_section += f"      ingestion_strategy: {agent.get('rag_ingestion', 'recursive')}\n"
            agents_section += f"      retrieval_strategy: {agent.get('rag_retrieval', 'simple')}\n"

        parallel = agent.get("execution_hints_parallel", True)
        agents_section += "    execution_hints:\n"
        agents_section += f"      parallel_safe: {'true' if parallel else 'false'}\n"
        agents_section += "\n"

    events = answers.get("events", {})
    events_section = ""
    if events.get("enabled", False):
        events_section = """events:
  enabled: true

  store:
    class: orchid_ai.events.backends.sqlite.SQLiteEventStorage
    extra_args:
      dsn: ~/.orchid/chats.db

  queue:
    class: orchid_ai.events.queues.sqlite.SQLiteSignalQueue
    poll_interval_ms: 200
    lease_seconds: 30
    max_attempts: 3

  scheduler:
    class: orchid_ai.events.schedulers.apscheduler.APSchedulerBackend

  producers:
    - class: orchid_ai.events.producers.scheduler.SchedulerProducer
    - class: orchid_ai.events.producers.internal.InternalEmissionProducer

  processors:
    - class: orchid_ai.events.processors.asyncio_pool.AsyncioWorkerPoolProcessor
      concurrency: 1
"""

    mcp_gateway = answers.get("_mcp_gateway", {})
    mcp_gateway_section = ""
    if mcp_gateway.get("configure", False):
        mcp_gateway_section = "mcp_gateway:\n  tools: {}\n"

    return AGENTS_YAML_TEMPLATE.format(
        defaults_llm_model=defaults_model,
        defaults_llm_temperature=0.2,
        defaults_rag_enabled=defaults_rag,
        guardrails_section=guardrails_section if guardrails_section else "# No global guardrails configured\n",
        tools_section=tools_section if tools_section else "# No global tools configured\n",
        skills_section=skills_section if skills_section else "# No cross-agent skills configured\n",
        agents_section=agents_section if agents_section else "  # No agents configured\n",
        mcp_gateway_section=mcp_gateway_section if mcp_gateway_section else "# No MCP gateway overrides\n",
        events_section=events_section if events_section else "# No events configured\n",
    )
