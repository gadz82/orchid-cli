from __future__ import annotations

from typing import Any

from .templates import (
    AGENT_PY_TEMPLATE,
    HOOK_PY_TEMPLATE,
    IDENTITY_PY_TEMPLATE,
    INIT_PY_TEMPLATE,
    README_MD_TEMPLATE,
    STORAGE_PY_TEMPLATE,
    TEST_AGENTS_PY_TEMPLATE,
    TOOL_PY_TEMPLATE,
    _build_agents_yaml,
    _build_orchid_yml,
)


class ScaffoldGenerator:
    def __init__(self, answers: dict[str, Any], project_name: str) -> None:
        self.answers = answers
        self.project_name = project_name

    def generate(self) -> dict[str, str]:
        files: dict[str, str] = {}

        files[f"{self.project_name}/__init__.py"] = INIT_PY_TEMPLATE.format(
            project_name=self.project_name,
            project_description=self.answers.get("project.description", "An Orchid AI project"),
        )
        files[f"{self.project_name}/orchid.yml"] = _build_orchid_yml(self.answers)
        files[f"{self.project_name}/agents.yaml"] = _build_agents_yaml(self.answers)
        files[f"{self.project_name}/README.md"] = README_MD_TEMPLATE.format(
            project_name=self.project_name,
            project_description=self.answers.get("project.description", "An Orchid AI project"),
        )
        files[f"{self.project_name}/agents/__init__.py"] = INIT_PY_TEMPLATE.format(
            project_name=f"{self.project_name}.agents",
            project_description="Custom agent classes",
        )
        files[f"{self.project_name}/tools/__init__.py"] = INIT_PY_TEMPLATE.format(
            project_name=f"{self.project_name}.tools",
            project_description="Built-in tool handlers",
        )
        files[f"{self.project_name}/tests/__init__.py"] = INIT_PY_TEMPLATE.format(
            project_name=f"{self.project_name}.tests",
            project_description="Tests",
        )
        files[f"{self.project_name}/tests/test_agents.py"] = TEST_AGENTS_PY_TEMPLATE

        auth_mode = self.answers.get("infrastructure.auth_mode", "dev_bypass")
        if auth_mode == "custom":
            resolver_class = self.answers.get("infrastructure.identity_resolver_class", "")
            if resolver_class:
                class_name = resolver_class.split(".")[-1]
                files[f"{self.project_name}/identity.py"] = IDENTITY_PY_TEMPLATE.format(class_name=class_name)

        startup_hook = self.answers.get("infrastructure.startup_hook_path", "")
        if startup_hook:
            hook_name = startup_hook.split(".")[-1]
            files[f"{self.project_name}/hooks/__init__.py"] = INIT_PY_TEMPLATE.format(
                project_name=f"{self.project_name}.hooks",
                project_description="Startup hooks",
            )
            files[f"{self.project_name}/hooks/{hook_name}.py"] = HOOK_PY_TEMPLATE.format(
                hook_name=hook_name,
                project_name=self.project_name,
            )

        storage_backend = self.answers.get("infrastructure.storage_backend", "sqlite")
        if storage_backend == "custom":
            storage_class = self.answers.get("infrastructure.storage_class", "")
            if storage_class:
                class_name = storage_class.split(".")[-1]
                files[f"{self.project_name}/storage/__init__.py"] = INIT_PY_TEMPLATE.format(
                    project_name=f"{self.project_name}.storage",
                    project_description="Custom storage backends",
                )
                files[f"{self.project_name}/storage/{class_name.lower()}.py"] = STORAGE_PY_TEMPLATE.format(
                    class_name=class_name,
                )

        for agent in self.answers.get("_agents", []):
            if agent.get("agent_type") == "custom" and agent.get("class_path"):
                class_name = agent["class_path"].split(".")[-1]
                files[f"{self.project_name}/agents/{agent['name']}.py"] = AGENT_PY_TEMPLATE.format(
                    class_name=class_name,
                )

        for tool in self.answers.get("_tools", []):
            handler_path = tool.get("handler", "")
            handler_name = handler_path.split(".")[-1] if handler_path else tool["name"]
            files[f"{self.project_name}/tools/{tool['name']}.py"] = TOOL_PY_TEMPLATE.format(
                handler_name=handler_name,
                description=tool.get("description", ""),
            )

        return files
