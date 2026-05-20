from __future__ import annotations

import ast
import zipfile
from pathlib import Path

import yaml

from orchid_cli.commands._flower.questions import (
    Question,
    QuestionType,
    _embedding_default,
    _skip_if_dev_bypass,
    _skip_if_null_vector,
    _skip_if_sqlite_storage,
)
from orchid_cli.commands._flower.scaffolding import ScaffoldGenerator
from orchid_cli.commands._flower.templates import _build_agents_yaml, _build_orchid_yml
from orchid_cli.commands._flower.validators import (
    validate_agent_config,
    validate_agent_name,
    validate_dotted_path,
    validate_full_config,
    validate_model,
    validate_number_range,
    validate_path_writable,
    validate_required,
    validate_url,
    validate_yaml_safe,
)


class TestValidators:
    def test_validate_dotted_path_valid(self) -> None:
        valid, _ = validate_dotted_path("myproject.agents.MyAgent")
        assert valid

    def test_validate_dotted_path_invalid(self) -> None:
        valid, err = validate_dotted_path("not-a-path")
        assert not valid
        assert "Invalid Python dotted path" in err

    def test_validate_dotted_path_empty(self) -> None:
        valid, err = validate_dotted_path("")
        assert not valid

    def test_validate_url_valid(self) -> None:
        valid, _ = validate_url("http://localhost:6333")
        assert valid

    def test_validate_url_invalid(self) -> None:
        valid, err = validate_url("not-a-url")
        assert not valid

    def test_validate_model_valid(self) -> None:
        valid, _ = validate_model("openai/gpt-4o")
        assert valid

    def test_validate_model_invalid(self) -> None:
        valid, err = validate_model("gpt-4o")
        assert not valid
        assert "provider/model format" in err

    def test_validate_agent_name_valid(self) -> None:
        valid, _ = validate_agent_name("basketball")
        assert valid

    def test_validate_agent_name_invalid_underscore(self) -> None:
        valid, err = validate_agent_name("my_agent")
        assert not valid
        assert "lowercase letters only" in err

    def test_validate_agent_name_invalid_upper(self) -> None:
        valid, err = validate_agent_name("Basketball")
        assert not valid

    def test_validate_agent_name_empty(self) -> None:
        valid, err = validate_agent_name("")
        assert not valid

    def test_validate_yaml_safe_valid(self) -> None:
        valid, _ = validate_yaml_safe("hello world")
        assert valid

    def test_validate_number_range_valid(self) -> None:
        valid, _ = validate_number_range("50", 0, 100)
        assert valid

    def test_validate_number_range_invalid(self) -> None:
        valid, err = validate_number_range("200", 0, 100)
        assert not valid
        assert "between" in err

    def test_validate_number_range_not_number(self) -> None:
        valid, err = validate_number_range("abc", 0, 100)
        assert not valid

    def test_validate_required_valid(self) -> None:
        valid, _ = validate_required("hello")
        assert valid

    def test_validate_required_empty(self) -> None:
        valid, err = validate_required("   ")
        assert not valid

    def test_validate_path_writable(self, tmp_path: Path) -> None:
        valid, _ = validate_path_writable(str(tmp_path / "new_dir"))
        assert valid

    def test_validate_full_config_valid(self) -> None:
        answers = {
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.vector_backend": "qdrant",
            "infrastructure.embedding_model": "ollama/nomic-embed-text",
            "_agents": [
                {
                    "name": "testagent",
                    "description": "A test agent",
                    "prompt": "You are a test agent",
                    "agent_type": "GenericAgent",
                }
            ],
        }
        valid, errors = validate_full_config(answers)
        assert valid
        assert errors == []

    def test_validate_full_config_no_agents(self) -> None:
        answers = {
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.vector_backend": "qdrant",
            "_agents": [],
        }
        valid, errors = validate_full_config(answers)
        assert not valid
        assert any("At least one agent" in e for e in errors)

    def test_validate_full_config_bad_model(self) -> None:
        answers = {
            "infrastructure.llm_model": "badmodel",
            "infrastructure.vector_backend": "qdrant",
            "_agents": [
                {
                    "name": "testagent",
                    "description": "A test agent",
                    "prompt": "You are a test agent",
                }
            ],
        }
        valid, errors = validate_full_config(answers)
        assert not valid
        assert any("provider/model format" in e for e in errors)

    def test_validate_agent_config_valid(self) -> None:
        config = {
            "description": "Test agent",
            "prompt": "You are a test agent",
        }
        valid, errors = validate_agent_config("testagent", config)
        assert valid

    def test_validate_agent_config_missing_description(self) -> None:
        config = {"prompt": "You are a test agent"}
        valid, errors = validate_agent_config("testagent", config)
        assert not valid
        assert any("description" in e for e in errors)

    def test_validate_agent_config_bad_class_path(self) -> None:
        config = {
            "description": "Test agent",
            "prompt": "You are a test agent",
            "class_path": "not-a-path",
        }
        valid, errors = validate_agent_config("testagent", config)
        assert not valid
        assert any("dotted path" in e.lower() for e in errors)


class TestQuestions:
    def test_embedding_default_ollama(self) -> None:
        answers = {"llm.provider": "ollama"}
        assert _embedding_default(answers) == "ollama/nomic-embed-text"

    def test_embedding_default_openai(self) -> None:
        answers = {"llm.provider": "openai"}
        assert _embedding_default(answers) == "text-embedding-3-small"

    def test_embedding_default_gemini(self) -> None:
        answers = {"llm.provider": "gemini"}
        assert _embedding_default(answers) == "gemini/gemini-embedding-001"

    def test_skip_if_null_vector_true(self) -> None:
        answers = {"infrastructure": {"vector_backend": "null"}}
        assert _skip_if_null_vector(answers) is True

    def test_skip_if_null_vector_false(self) -> None:
        answers = {"infrastructure": {"vector_backend": "qdrant"}}
        assert _skip_if_null_vector(answers) is False

    def test_skip_if_dev_bypass_true(self) -> None:
        answers = {"infrastructure.auth_mode": "dev_bypass"}
        assert _skip_if_dev_bypass(answers) is True

    def test_skip_if_dev_bypass_false(self) -> None:
        answers = {"infrastructure.auth_mode": "custom"}
        assert _skip_if_dev_bypass(answers) is False

    def test_skip_if_sqlite_storage_true(self) -> None:
        answers = {"infrastructure.storage_backend": "sqlite"}
        assert _skip_if_sqlite_storage(answers) is True

    def test_skip_if_sqlite_storage_false(self) -> None:
        answers = {"infrastructure.storage_backend": "custom"}
        assert _skip_if_sqlite_storage(answers) is False

    def test_question_dataclass(self) -> None:
        q = Question(
            key="test.key",
            prompt="Test?",
            type=QuestionType.SELECT,
            choices=["a", "b"],
            default="a",
        )
        assert q.key == "test.key"
        assert q.choices == ["a", "b"]
        assert q.default == "a"


class TestTemplates:
    def test_build_orchid_yml_valid(self) -> None:
        answers = {
            "project.name": "testproject",
            "project.description": "A test project",
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.llm_provider": "ollama",
            "infrastructure.ollama_api_base": "http://localhost:11434",
            "infrastructure.auth_mode": "dev_bypass",
            "infrastructure.vector_backend": "qdrant",
            "infrastructure.qdrant_url": "http://localhost:6333",
            "infrastructure.embedding_model": "ollama/nomic-embed-text",
            "infrastructure.vision_model": "ollama/minicpm-v",
            "infrastructure.upload_namespace": "uploads",
            "infrastructure.upload_max_size_mb": 20,
            "infrastructure.chunk_size": 1000,
            "infrastructure.chunk_overlap": 200,
            "infrastructure.storage_backend": "sqlite",
            "infrastructure.storage_dsn": "~/.orchid/chats.db",
            "infrastructure.checkpointer": "memory",
            "infrastructure.langsmith_tracing": False,
        }
        result = _build_orchid_yml(answers)
        data = yaml.safe_load(result)
        assert data is not None
        assert "llm" in data
        assert "rag" in data
        assert "storage" in data

    def test_build_orchid_yml_null_vector(self) -> None:
        answers = {
            "project.name": "testproject",
            "project.description": "A test project",
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.auth_mode": "dev_bypass",
            "infrastructure.vector_backend": "null",
            "infrastructure.vision_model": "ollama/minicpm-v",
            "infrastructure.upload_namespace": "uploads",
            "infrastructure.upload_max_size_mb": 20,
            "infrastructure.chunk_size": 1000,
            "infrastructure.chunk_overlap": 200,
            "infrastructure.storage_backend": "sqlite",
            "infrastructure.storage_dsn": "~/.orchid/chats.db",
            "infrastructure.checkpointer": "memory",
            "infrastructure.langsmith_tracing": False,
        }
        result = _build_orchid_yml(answers)
        data = yaml.safe_load(result)
        assert data is not None
        assert "embedding_model" not in data.get("rag", {})

    def test_build_agents_yaml_valid(self) -> None:
        answers = {
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.vector_backend": "qdrant",
            "_agents": [
                {
                    "name": "testagent",
                    "description": "A test agent",
                    "prompt": "You are a test agent",
                    "agent_type": "GenericAgent",
                    "tools": ["tool1"],
                    "rag_enabled": False,
                    "execution_hints_parallel": True,
                }
            ],
            "_tools": [],
            "_skills": [],
            "_guardrails": {"input": [], "output": []},
            "events": {"enabled": False},
            "_mcp_gateway": {"configure": False},
        }
        result = _build_agents_yaml(answers)
        data = yaml.safe_load(result)
        assert data is not None
        assert "agents" in data
        assert "testagent" in data["agents"]

    def test_build_agents_yaml_with_guardrails(self) -> None:
        answers = {
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.vector_backend": "qdrant",
            "_agents": [],
            "_tools": [],
            "_skills": [],
            "_guardrails": {
                "input": [{"type": "prompt_injection", "fail_action": "block"}],
                "output": [{"type": "pii_detection", "fail_action": "redact", "config": {"entities": ["email"]}}],
            },
            "events": {"enabled": False},
            "_mcp_gateway": {"configure": False},
        }
        result = _build_agents_yaml(answers)
        data = yaml.safe_load(result)
        assert data is not None
        assert "guardrails" in data


class TestScaffolding:
    def test_generate_basic_structure(self) -> None:
        answers = {
            "project.name": "testproject",
            "project.description": "A test project",
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.auth_mode": "dev_bypass",
            "infrastructure.vector_backend": "qdrant",
            "infrastructure.storage_backend": "sqlite",
            "infrastructure.storage_dsn": "~/.orchid/chats.db",
            "infrastructure.vision_model": "ollama/minicpm-v",
            "infrastructure.upload_namespace": "uploads",
            "infrastructure.upload_max_size_mb": 20,
            "infrastructure.chunk_size": 1000,
            "infrastructure.chunk_overlap": 200,
            "infrastructure.checkpointer": "memory",
            "infrastructure.langsmith_tracing": False,
            "_agents": [
                {
                    "name": "testagent",
                    "description": "A test agent",
                    "prompt": "You are a test agent",
                    "agent_type": "GenericAgent",
                    "rag_enabled": False,
                    "execution_hints_parallel": True,
                }
            ],
            "_tools": [],
            "_skills": [],
            "_guardrails": {"input": [], "output": []},
            "events": {"enabled": False},
            "_mcp_gateway": {"configure": False},
        }
        scaffold = ScaffoldGenerator(answers, "testproject")
        files = scaffold.generate()

        assert "testproject/__init__.py" in files
        assert "testproject/orchid.yml" in files
        assert "testproject/agents.yaml" in files
        assert "testproject/README.md" in files
        assert "testproject/agents/__init__.py" in files
        assert "testproject/tools/__init__.py" in files
        assert "testproject/tests/__init__.py" in files
        assert "testproject/tests/test_agents.py" in files

    def test_generated_yaml_is_valid(self) -> None:
        answers = {
            "project.name": "testproject",
            "project.description": "A test project",
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.auth_mode": "dev_bypass",
            "infrastructure.vector_backend": "qdrant",
            "infrastructure.storage_backend": "sqlite",
            "infrastructure.storage_dsn": "~/.orchid/chats.db",
            "infrastructure.vision_model": "ollama/minicpm-v",
            "infrastructure.upload_namespace": "uploads",
            "infrastructure.upload_max_size_mb": 20,
            "infrastructure.chunk_size": 1000,
            "infrastructure.chunk_overlap": 200,
            "infrastructure.checkpointer": "memory",
            "infrastructure.langsmith_tracing": False,
            "_agents": [
                {
                    "name": "testagent",
                    "description": "A test agent",
                    "prompt": "You are a test agent",
                    "agent_type": "GenericAgent",
                    "rag_enabled": False,
                    "execution_hints_parallel": True,
                }
            ],
            "_tools": [],
            "_skills": [],
            "_guardrails": {"input": [], "output": []},
            "events": {"enabled": False},
            "_mcp_gateway": {"configure": False},
        }
        scaffold = ScaffoldGenerator(answers, "testproject")
        files = scaffold.generate()

        orchid_yml = yaml.safe_load(files["testproject/orchid.yml"])
        assert orchid_yml is not None

        agents_yaml = yaml.safe_load(files["testproject/agents.yaml"])
        assert agents_yaml is not None

    def test_generated_python_is_valid(self) -> None:
        answers = {
            "project.name": "testproject",
            "project.description": "A test project",
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.auth_mode": "dev_bypass",
            "infrastructure.vector_backend": "qdrant",
            "infrastructure.storage_backend": "sqlite",
            "infrastructure.storage_dsn": "~/.orchid/chats.db",
            "infrastructure.vision_model": "ollama/minicpm-v",
            "infrastructure.upload_namespace": "uploads",
            "infrastructure.upload_max_size_mb": 20,
            "infrastructure.chunk_size": 1000,
            "infrastructure.chunk_overlap": 200,
            "infrastructure.checkpointer": "memory",
            "infrastructure.langsmith_tracing": False,
            "infrastructure.identity_resolver_class": "testproject.identity.MyResolver",
            "infrastructure.startup_hook_path": "testproject.hooks.on_startup",
            "_agents": [
                {
                    "name": "testagent",
                    "description": "A test agent",
                    "prompt": "You are a test agent",
                    "agent_type": "custom",
                    "class_path": "testproject.agents.TestAgent",
                    "rag_enabled": False,
                    "execution_hints_parallel": True,
                }
            ],
            "_tools": [
                {
                    "name": "my_tool",
                    "handler": "testproject.tools.my_tool.my_tool_handler",
                    "description": "A test tool",
                    "parameters": {},
                }
            ],
            "_skills": [],
            "_guardrails": {"input": [], "output": []},
            "events": {"enabled": False},
            "_mcp_gateway": {"configure": False},
        }
        scaffold = ScaffoldGenerator(answers, "testproject")
        files = scaffold.generate()

        for filepath, content in files.items():
            if filepath.endswith(".py"):
                ast.parse(content)

    def test_custom_identity_scaffold(self) -> None:
        answers = {
            "project.name": "testproject",
            "project.description": "A test project",
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.auth_mode": "custom",
            "infrastructure.identity_resolver_class": "testproject.identity.MyResolver",
            "infrastructure.vector_backend": "qdrant",
            "infrastructure.storage_backend": "sqlite",
            "infrastructure.storage_dsn": "~/.orchid/chats.db",
            "infrastructure.vision_model": "ollama/minicpm-v",
            "infrastructure.upload_namespace": "uploads",
            "infrastructure.upload_max_size_mb": 20,
            "infrastructure.chunk_size": 1000,
            "infrastructure.chunk_overlap": 200,
            "infrastructure.checkpointer": "memory",
            "infrastructure.langsmith_tracing": False,
            "_agents": [],
            "_tools": [],
            "_skills": [],
            "_guardrails": {"input": [], "output": []},
            "events": {"enabled": False},
            "_mcp_gateway": {"configure": False},
        }
        scaffold = ScaffoldGenerator(answers, "testproject")
        files = scaffold.generate()
        assert "testproject/identity.py" in files
        assert "MyResolver" in files["testproject/identity.py"]


class TestOutput:
    def test_create_zip(self, tmp_path: Path) -> None:
        from orchid_cli.commands._flower.output import create_zip

        file_tree = {
            "testproject/orchid.yml": "llm:\n  model: test\n",
            "testproject/agents.yaml": "version: '1'\n",
        }
        output_path = tmp_path / "testproject"
        zip_path = create_zip(file_tree, output_path)

        assert zip_path.exists()
        assert zip_path.suffix == ".zip"

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "testproject/orchid.yml" in names
            assert "testproject/agents.yaml" in names

    def test_write_to_directory(self, tmp_path: Path) -> None:
        from orchid_cli.commands._flower.output import write_to_directory

        file_tree = {
            "testproject/orchid.yml": "llm:\n  model: test\n",
            "testproject/agents.yaml": "version: '1'\n",
        }
        write_to_directory(file_tree, tmp_path)

        assert (tmp_path / "testproject/orchid.yml").exists()
        assert (tmp_path / "testproject/agents.yaml").exists()

    def test_display_file_tree(self) -> None:
        from rich.console import Console
        from orchid_cli.commands._flower.output import display_file_tree

        file_tree = {
            "testproject/orchid.yml": "content",
            "testproject/agents/__init__.py": "content",
        }
        console = Console(force_terminal=True)
        display_file_tree(file_tree, console=console)
