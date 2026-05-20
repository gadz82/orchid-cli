from __future__ import annotations

from typing import Any

from rich.console import Console

from .questions import (
    ALL_PHASES,
    PHASE_3_AGENT_LOOP,
    PHASE_4_GLOBAL_TOOLS,
    PHASE_5_SKILLS,
    PHASE_6_GUARDRAILS,
    PHASE_7_EVENTS,
    PHASE_8_MCP_GATEWAY,
    Phase,
    Question,
    QuestionType,
)
from .validators import (
    validate_agent_name,
)


class Wizard:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()
        self.answers: dict[str, Any] = {}
        self._history: list[tuple[str, Any]] = []

    def get_nested(self, key: str) -> Any:
        parts = key.split(".")
        current: Any = self.answers
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current

    def set_nested(self, key: str, value: Any) -> None:
        parts = key.split(".")
        current = self.answers
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    def should_skip(self, question: Question) -> bool:
        if question.condition is None:
            return False
        return not question.condition(self.answers)

    def _resolve_default(self, question: Question) -> Any:
        if callable(question.default):
            return question.default(self.answers)
        return question.default

    def ask_question(self, question: Question) -> Any:
        if self.should_skip(question):
            return None

        default = self._resolve_default(question)
        existing = self.get_nested(question.key)
        if existing is not None:
            default = existing

        self.console.print()
        self.console.print(f"[bold cyan]?[/bold cyan] {question.prompt}")

        if question.help_text:
            self.console.print(f"  [dim]{question.help_text}[/dim]")

        if question.type == QuestionType.SELECT and question.choices:
            return self._ask_select(question, default)
        elif question.type == QuestionType.MULTI_SELECT and question.choices:
            return self._ask_multi_select(question, default)
        elif question.type == QuestionType.BOOL:
            return self._ask_bool(question, default)
        elif question.type == QuestionType.NUMBER:
            return self._ask_number(question, default)
        elif question.type == QuestionType.LONG_TEXT:
            return self._ask_long_text(question, default)
        else:
            return self._ask_text(question, default)

    def _ask_select(self, question: Question, default: Any) -> str:
        assert question.choices is not None
        for i, choice in enumerate(question.choices, 1):
            marker = " (default)" if choice == default else ""
            self.console.print(f"  [yellow]{i}[/yellow]. {choice}{marker}")

        default_idx = question.choices.index(default) + 1 if default in question.choices else 1
        while True:
            raw = self.console.input(f"  [green]>[/green] [{default_idx}]: ").strip()
            if raw == "":
                return str(default)
            if raw.lower() == "back":
                return "BACK"
            if raw.lower() == "skip":
                return str(default)
            try:
                idx = int(raw)
                if 1 <= idx <= len(question.choices):
                    return question.choices[idx - 1]
                self.console.print("  [red]Invalid selection. Try again.[/red]")
            except ValueError:
                self.console.print("  [red]Please enter a number.[/red]")

    def _ask_multi_select(self, question: Question, default: Any) -> list[str]:
        assert question.choices is not None
        for i, choice in enumerate(question.choices, 1):
            self.console.print(f"  [yellow]{i}[/yellow]. {choice}")
        self.console.print("  [dim](comma-separated numbers, e.g. 1,3,5)[/dim]")

        while True:
            raw = self.console.input("  [green]>[/green] ").strip()
            if raw.lower() == "back":
                return "BACK"
            if raw == "":
                return default if isinstance(default, list) else []
            try:
                indices = [int(x.strip()) for x in raw.split(",")]
                result = []
                valid = True
                for idx in indices:
                    if 1 <= idx <= len(question.choices):
                        result.append(question.choices[idx - 1])
                    else:
                        self.console.print(f"  [red]Invalid selection: {idx}[/red]")
                        valid = False
                        break
                if valid:
                    return result
            except ValueError:
                self.console.print("  [red]Please enter comma-separated numbers.[/red]")

    def _ask_bool(self, question: Question, default: Any) -> bool:
        default_bool = bool(default)
        prompt_suffix = "Y/n" if default_bool else "y/N"
        while True:
            raw = self.console.input(f"  [green]>[/green] ({prompt_suffix}): ").strip().lower()
            if raw == "":
                return default_bool
            if raw == "back":
                return "BACK"
            if raw == "skip":
                return default_bool
            if raw in ("y", "yes", "true", "1"):
                return True
            if raw in ("n", "no", "false", "0"):
                return False
            self.console.print("  [red]Please enter y or n.[/red]")

    def _ask_number(self, question: Question, default: Any) -> int | float:
        while True:
            raw = self.console.input(f"  [green]>[/green] [{default}]: ").strip()
            if raw == "":
                return default
            if raw.lower() == "back":
                return "BACK"
            if raw.lower() == "skip":
                return default
            try:
                return int(raw) if "." not in raw else float(raw)
            except ValueError:
                self.console.print("  [red]Please enter a valid number.[/red]")

    def _ask_text(self, question: Question, default: Any) -> str:
        default_str = str(default) if default is not None else ""
        while True:
            if default_str:
                raw = self.console.input(f"  [green]>[/green] [{default_str}]: ").strip()
            else:
                raw = self.console.input("  [green]>[/green] ").strip()

            if raw.lower() == "back":
                return "BACK"
            if raw.lower() == "skip":
                return default_str
            if raw == "":
                raw = default_str

            if question.validator:
                valid, error = question.validator(raw)
                if not valid:
                    self.console.print(f"  [red]{error}[/red]")
                    continue

            if question.type == QuestionType.TEXT:
                if question.key and "agent_name" in question.key:
                    valid, error = validate_agent_name(raw)
                    if not valid:
                        self.console.print(f"  [red]{error}[/red]")
                        continue

            return raw

    def _ask_long_text(self, question: Question, default: Any) -> str:
        self.console.print("  [dim](Enter text, press Ctrl+D or type END on a new line to finish)[/dim]")
        lines = []
        while True:
            try:
                line = input("  ... ")
                if line.strip() == "END":
                    break
                lines.append(line)
            except EOFError:
                break
        result = "\n".join(lines).strip()
        return result if result else str(default or "")

    def run_phase(self, phase: Phase, phase_num: int, total_phases: int) -> bool:
        if phase.condition and not phase.condition(self.answers):
            return True

        self.console.print()
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")
        self.console.print(f"[bold magenta]Phase {phase_num}/{total_phases}: {phase.name}[/bold magenta]")
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")

        for q in phase.questions:
            answer = self.ask_question(q)
            if answer == "BACK":
                return False
            if answer is None:
                continue
            self.set_nested(q.key, answer)
            self._history.append((q.key, answer))

        return True

    def _collect_agent(self) -> dict[str, Any] | None:
        self.console.print()
        self.console.print("[bold]--- New Agent ---[/bold]")

        agent: dict[str, Any] = {}

        name = self.console.input("  Agent name (lowercase, no underscores): ").strip()
        if not name:
            return None
        valid, error = validate_agent_name(name)
        if not valid:
            self.console.print(f"  [red]{error}[/red]")
            return None

        agent["name"] = name
        agent["description"] = self.console.input("  Description (for supervisor routing): ").strip()

        self.console.print("  System prompt (multi-line, END on new line to finish):")
        prompt_lines = []
        while True:
            try:
                line = input("    ... ")
                if line.strip() == "END":
                    break
                prompt_lines.append(line)
            except EOFError:
                break
        agent["prompt"] = "\n".join(prompt_lines).strip()

        agent_type = "GenericAgent"
        self.console.print("  Agent type: 1) GenericAgent  2) Custom class")
        type_choice = self.console.input("  [green]>[/green] [1]: ").strip()
        if type_choice == "2":
            agent_type = "custom"
            agent["class_path"] = self.console.input("  Custom class dotted path: ").strip()
        agent["agent_type"] = agent_type

        use_llm_override = self.console.input("  Override LLM model? (y/N): ").strip().lower()
        if use_llm_override in ("y", "yes"):
            agent["llm_model"] = self.console.input("  LLM model (provider/model): ").strip()
            agent["llm_temperature"] = self.console.input("  Temperature [0.2]: ").strip() or "0.2"

        use_rag = self.console.input("  Enable RAG for this agent? (y/N): ").strip().lower()
        if use_rag in ("y", "yes"):
            agent["rag_enabled"] = True
            agent["rag_namespace"] = self.console.input("  RAG namespace: ").strip() or name
            agent["rag_ingestion"] = self.console.input("  Ingestion strategy [recursive]: ").strip() or "recursive"
            agent["rag_retrieval"] = self.console.input("  Retrieval strategy [simple]: ").strip() or "simple"
        else:
            agent["rag_enabled"] = False

        agent["mcp_servers"] = []
        while True:
            add_mcp = self.console.input("  Add MCP server? (y/N): ").strip().lower()
            if add_mcp not in ("y", "yes"):
                break
            mcp: dict[str, Any] = {}
            mcp["name"] = self.console.input("    Server name: ").strip()
            mcp["url"] = self.console.input("    Server URL: ").strip()
            mcp["auth_mode"] = self.console.input("    Auth mode [none/passthrough/oauth]: ").strip() or "none"
            mcp["tools"] = self.console.input("    Tools (* for all, or comma-separated): ").strip() or "*"
            agent["mcp_servers"].append(mcp)

        agent["tools"] = []
        while True:
            add_tool = self.console.input("  Add built-in tool? (y/N): ").strip().lower()
            if add_tool not in ("y", "yes"):
                break
            tool_name = self.console.input("    Tool name: ").strip()
            if tool_name:
                agent["tools"].append(tool_name)

        agent["execution_hints_parallel"] = self.console.input("  Parallel safe? (Y/n): ").strip().lower()
        agent["execution_hints_parallel"] = agent["execution_hints_parallel"] not in ("n", "no")

        return agent

    def _collect_tool(self) -> dict[str, Any] | None:
        self.console.print()
        self.console.print("[bold]--- New Global Tool ---[/bold]")

        name = self.console.input("  Tool name: ").strip()
        if not name:
            return None

        tool: dict[str, Any] = {"name": name}
        tool["handler"] = self.console.input("  Handler dotted path: ").strip()
        tool["description"] = self.console.input("  Description: ").strip()

        tool["parameters"] = {}
        while True:
            add_param = self.console.input("  Add parameter? (y/N): ").strip().lower()
            if add_param not in ("y", "yes"):
                break
            param_name = self.console.input("    Parameter name: ").strip()
            if not param_name:
                continue
            param: dict[str, Any] = {}
            param["type"] = self.console.input("    Type [string]: ").strip() or "string"
            param["description"] = self.console.input("    Description: ").strip()
            param["required"] = self.console.input("    Required? (Y/n): ").strip().lower() not in ("n", "no")
            tool["parameters"][param_name] = param

        return tool

    def _collect_skill(self) -> dict[str, Any] | None:
        self.console.print()
        self.console.print("[bold]--- New Cross-Agent Skill ---[/bold]")

        name = self.console.input("  Skill name: ").strip()
        if not name:
            return None

        skill: dict[str, Any] = {"name": name}
        skill["description"] = self.console.input("  Description: ").strip()
        skill["steps"] = []

        while True:
            add_step = self.console.input("  Add step? (y/N): ").strip().lower()
            if add_step not in ("y", "yes"):
                break
            step: dict[str, Any] = {}
            step["agent"] = self.console.input("    Agent name: ").strip()
            step["instruction"] = self.console.input("    Instruction: ").strip()
            skill["steps"].append(step)

        return skill

    def run_all_phases(self) -> bool:
        total = len(ALL_PHASES)

        for i, phase in enumerate(ALL_PHASES, 1):
            if phase in (PHASE_3_AGENT_LOOP,):
                self._run_agent_loop()
                continue
            if phase in (PHASE_4_GLOBAL_TOOLS,):
                self._run_tools_loop()
                continue
            if phase in (PHASE_5_SKILLS,):
                self._run_skills_loop()
                continue
            if phase in (PHASE_6_GUARDRAILS,):
                self._run_guardrails()
                continue
            if phase in (PHASE_7_EVENTS,):
                self._run_events()
                continue
            if phase in (PHASE_8_MCP_GATEWAY,):
                self._run_mcp_gateway()
                continue

            success = self.run_phase(phase, i, total)
            if not success:
                return False

        return self._run_review()

    def _run_review(self) -> bool:
        from ._flower.validators import validate_full_config

        self.console.print()
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")
        self.console.print("[bold magenta]Review & Validate[/bold magenta]")
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")

        self.console.print()
        self.console.print("[bold]Summary:[/bold]")
        self.console.print(f"  Project: {self.get_nested('project.name')}")
        self.console.print(f"  Description: {self.get_nested('project.description')}")
        self.console.print(f"  LLM: {self.get_nested('infrastructure.llm_model')}")
        self.console.print(f"  Vector backend: {self.get_nested('infrastructure.vector_backend')}")
        self.console.print(f"  Storage: {self.get_nested('infrastructure.storage_backend')}")

        agents = self.answers.get("_agents", [])
        self.console.print(f"  Agents: {len(agents)}")
        for agent in agents:
            self.console.print(f"    - {agent.get('name')} ({agent.get('agent_type', 'GenericAgent')})")

        tools = self.answers.get("_tools", [])
        self.console.print(f"  Global tools: {len(tools)}")

        skills = self.answers.get("_skills", [])
        self.console.print(f"  Cross-agent skills: {len(skills)}")

        valid, errors = validate_full_config(self.answers)
        if valid:
            self.console.print("\n[bold green]✓ Configuration is valid[/bold green]")
        else:
            self.console.print("\n[bold red]✗ Validation errors:[/bold red]")
            for error in errors:
                self.console.print(f"  - {error}")

        while True:
            self.console.print()
            action = (
                self.console.input(
                    "[bold cyan]?[/bold cyan] Type 'generate' to create the package, 'edit <key>' to modify, 'quit' to cancel: "
                )
                .strip()
                .lower()
            )

            if action == "generate":
                if not valid:
                    confirm = (
                        self.console.input("  [yellow]Config has errors. Generate anyway? (y/N):[/yellow] ")
                        .strip()
                        .lower()
                    )
                    if confirm not in ("y", "yes"):
                        return False
                return True
            elif action == "quit":
                return False
            elif action.startswith("edit "):
                key = action[5:].strip()
                current = self.get_nested(key)
                new_val = self.console.input(f"  Current: {current}\n  New value: ").strip()
                if new_val:
                    self.set_nested(key, new_val)
                    valid, errors = validate_full_config(self.answers)
            else:
                self.console.print("  [red]Unknown command. Use 'generate', 'edit <key>', or 'quit'.[/red]")

    def _run_agent_loop(self) -> None:
        phase_num = 4
        total = len(ALL_PHASES)
        self.console.print()
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")
        self.console.print(f"[bold magenta]Phase {phase_num}/{total}: Agent Definition Loop[/bold magenta]")
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")

        agents: list[dict[str, Any]] = []
        while True:
            add = self.console.input("\n[bold cyan]?[/bold cyan] Add another agent? (Y/n): ").strip().lower()
            if add in ("n", "no"):
                break
            agent = self._collect_agent()
            if agent:
                agents.append(agent)

        self.answers["_agents"] = agents

    def _run_tools_loop(self) -> None:
        phase_num = 5
        total = len(ALL_PHASES)
        self.console.print()
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")
        self.console.print(f"[bold magenta]Phase {phase_num}/{total}: Global Tools Definition[/bold magenta]")
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")

        tools: list[dict[str, Any]] = []
        while True:
            add = self.console.input("\n[bold cyan]?[/bold cyan] Add another global tool? (y/N): ").strip().lower()
            if add not in ("y", "yes"):
                break
            tool = self._collect_tool()
            if tool:
                tools.append(tool)

        self.answers["_tools"] = tools

    def _run_skills_loop(self) -> None:
        phase_num = 6
        total = len(ALL_PHASES)
        self.console.print()
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")
        self.console.print(f"[bold magenta]Phase {phase_num}/{total}: Cross-Agent Skills[/bold magenta]")
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")

        skills: list[dict[str, Any]] = []
        while True:
            add = (
                self.console.input("\n[bold cyan]?[/bold cyan] Add another cross-agent skill? (y/N): ").strip().lower()
            )
            if add not in ("y", "yes"):
                break
            skill = self._collect_skill()
            if skill:
                skills.append(skill)

        self.answers["_skills"] = skills

    def _run_guardrails(self) -> None:
        phase_num = 7
        total = len(ALL_PHASES)
        self.console.print()
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")
        self.console.print(f"[bold magenta]Phase {phase_num}/{total}: Global Guardrails[/bold magenta]")
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")

        input_rules: list[dict[str, Any]] = []
        if self.console.input("\n[bold cyan]?[/bold cyan] Configure input guardrails? (Y/n): ").strip().lower() not in (
            "n",
            "no",
        ):
            for rule_type in ["prompt_injection", "content_safety", "max_length"]:
                add = self.console.input(f"  Add {rule_type} rule? (Y/n): ").strip().lower()
                if add not in ("n", "no"):
                    rule: dict[str, Any] = {"type": rule_type, "fail_action": "block"}
                    if rule_type == "max_length":
                        rule["config"] = {"max_characters": 5000}
                    input_rules.append(rule)

        output_rules: list[dict[str, Any]] = []
        if self.console.input(
            "\n[bold cyan]?[/bold cyan] Configure output guardrails? (Y/n): "
        ).strip().lower() not in ("n", "no"):
            add = self.console.input("  Add pii_detection rule? (Y/n): ").strip().lower()
            if add not in ("n", "no"):
                output_rules.append(
                    {"type": "pii_detection", "fail_action": "redact", "config": {"entities": ["email", "phone"]}}
                )

        self.answers["_guardrails"] = {"input": input_rules, "output": output_rules}

    def _run_events(self) -> None:
        phase_num = 8
        total = len(ALL_PHASES)
        self.console.print()
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")
        self.console.print(f"[bold magenta]Phase {phase_num}/{total}: Events (Pollen + Bloom)[/bold magenta]")
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")

        enabled = self.console.input("\n[bold cyan]?[/bold cyan] Enable events? (y/N): ").strip().lower()
        self.answers["events"] = {"enabled": enabled in ("y", "yes")}

    def _run_mcp_gateway(self) -> None:
        phase_num = 9
        total = len(ALL_PHASES)
        self.console.print()
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")
        self.console.print(f"[bold magenta]Phase {phase_num}/{total}: MCP Gateway Customization[/bold magenta]")
        self.console.print(f"[bold magenta]{'=' * 60}[/bold magenta]")

        configure = (
            self.console.input("\n[bold cyan]?[/bold cyan] Configure MCP gateway overrides? (y/N): ").strip().lower()
        )
        self.answers["_mcp_gateway"] = {"configure": configure in ("y", "yes")}
