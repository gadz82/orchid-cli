from __future__ import annotations

import ast
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from orchid_cli.commands._flower.ai_assistant import AIAssistant
from orchid_cli.commands._flower.questions import (
    ALL_PHASES,
    PHASE_0_IDENTITY,
    PHASE_1_INFRASTRUCTURE,
    PHASE_2_SUPERVISOR,
    Phase,
    Question,
    QuestionType,
    _embedding_default,
    _skip_if_dev_bypass,
    _skip_if_no_startup_hook,
    _skip_if_no_tracing,
    _skip_if_null_vector,
    _skip_if_null_vector_url,
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
    validate_path_exists,
    validate_path_writable,
    validate_required,
    validate_url,
    validate_yaml_safe,
)
from orchid_cli.commands._flower.wizard import Wizard


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


class TestAIAssistant:
    def test_explain_option(self) -> None:
        assistant = AIAssistant(model="ollama/llama3.2")
        q = Question(key="test", prompt="What is this?", type=QuestionType.TEXT, help_text="Help me")
        with patch.object(assistant, "_complete", return_value="This is a test option."):
            result = assistant.explain_option(q)
            assert "test option" in result

    def test_explain_option_with_choices(self) -> None:
        assistant = AIAssistant(model="ollama/llama3.2")
        q = Question(key="test", prompt="Choose one", type=QuestionType.SELECT, choices=["a", "b"])
        with patch.object(assistant, "_complete", return_value="Option A is for X."):
            result = assistant.explain_option(q)
            assert "Option A" in result

    def test_explain_option_fallback(self) -> None:
        assistant = AIAssistant(model="ollama/llama3.2")
        q = Question(key="test", prompt="What?", type=QuestionType.TEXT)
        with patch.object(assistant, "_complete", side_effect=Exception("fail")):
            result = assistant.explain_option(q)
            assert "unavailable" in result

    def test_suggest_value(self) -> None:
        assistant = AIAssistant(model="ollama/llama3.2")
        q = Question(key="test", prompt="Pick model", type=QuestionType.TEXT, default="ollama/llama3.2")
        with patch.object(assistant, "_complete", return_value="openai/gpt-4o"):
            result = assistant.suggest_value(q, {"infrastructure.llm_provider": "openai"})
            assert "gpt-4o" in result

    def test_suggest_value_fallback(self) -> None:
        assistant = AIAssistant(model="ollama/llama3.2")
        q = Question(key="test", prompt="Pick", type=QuestionType.TEXT, default="default_val")
        with patch.object(assistant, "_complete", side_effect=Exception("fail")):
            result = assistant.suggest_value(q, {})
            assert result == "default_val"

    def test_suggest_value_no_default(self) -> None:
        assistant = AIAssistant(model="ollama/llama3.2")
        q = Question(key="test", prompt="Pick", type=QuestionType.TEXT)
        with patch.object(assistant, "_complete", side_effect=Exception("fail")):
            result = assistant.suggest_value(q, {})
            assert result == ""

    def test_validate_choice_yes(self) -> None:
        assistant = AIAssistant(model="ollama/llama3.2")
        q = Question(key="test", prompt="Model?", type=QuestionType.TEXT)
        with patch.object(assistant, "_complete", return_value="YES"):
            valid, _ = assistant.validate_choice("ollama/llama3.2", q)
            assert valid is True

    def test_validate_choice_no(self) -> None:
        assistant = AIAssistant(model="ollama/llama3.2")
        q = Question(key="test", prompt="Model?", type=QuestionType.TEXT, choices=["a", "b"])
        with patch.object(assistant, "_complete", return_value="NO: bad choice"):
            valid, err = assistant.validate_choice("c", q)
            assert valid is False
            assert "bad choice" in err

    def test_validate_choice_fallback(self) -> None:
        assistant = AIAssistant(model="ollama/llama3.2")
        q = Question(key="test", prompt="Model?", type=QuestionType.TEXT)
        with patch.object(assistant, "_complete", side_effect=Exception("fail")):
            valid, _ = assistant.validate_choice("anything", q)
            assert valid is True

    def test_complete(self) -> None:
        assistant = AIAssistant(model="ollama/llama3.2")
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Hello"))]
        with patch("litellm.completion", return_value=mock_response) as mock_call:
            result = assistant._complete("Say hello")
            assert result == "Hello"
            mock_call.assert_called_once()

    def test_complete_empty_response(self) -> None:
        assistant = AIAssistant(model="ollama/llama3.2")
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=None))]
        with patch("litellm.completion", return_value=mock_response):
            result = assistant._complete("Test")
            assert result == ""


class TestWizard:
    def test_get_nested_simple(self) -> None:
        wizard = Wizard()
        wizard.answers = {"a": {"b": "c"}}
        assert wizard.get_nested("a.b") == "c"

    def test_get_nested_missing(self) -> None:
        wizard = Wizard()
        wizard.answers = {"a": {"b": "c"}}
        assert wizard.get_nested("a.x") is None

    def test_get_nested_deep_missing(self) -> None:
        wizard = Wizard()
        wizard.answers = {"a": {"b": "c"}}
        assert wizard.get_nested("a.b.c.d") is None

    def test_set_nested_simple(self) -> None:
        wizard = Wizard()
        wizard.set_nested("a.b", "c")
        assert wizard.answers == {"a": {"b": "c"}}

    def test_set_nested_deep(self) -> None:
        wizard = Wizard()
        wizard.set_nested("a.b.c", "d")
        assert wizard.answers["a"]["b"]["c"] == "d"

    def test_set_nested_overwrite(self) -> None:
        wizard = Wizard()
        wizard.set_nested("a.b", "old")
        wizard.set_nested("a.b", "new")
        assert wizard.answers["a"]["b"] == "new"

    def test_should_skip_no_condition(self) -> None:
        wizard = Wizard()
        q = Question(key="test", prompt="Test?", type=QuestionType.TEXT)
        assert wizard.should_skip(q) is False

    def test_should_skip_condition_true(self) -> None:
        wizard = Wizard()
        wizard.answers = {"skip": True}
        q = Question(key="test", prompt="Test?", type=QuestionType.TEXT, condition=lambda a: a.get("skip"))
        assert wizard.should_skip(q) is False

    def test_should_skip_condition_false(self) -> None:
        wizard = Wizard()
        wizard.answers = {"skip": False}
        q = Question(key="test", prompt="Test?", type=QuestionType.TEXT, condition=lambda a: a.get("skip"))
        assert wizard.should_skip(q) is True

    def test_resolve_default_static(self) -> None:
        wizard = Wizard()
        q = Question(key="test", prompt="Test?", type=QuestionType.TEXT, default="hello")
        assert wizard._resolve_default(q) == "hello"

    def test_resolve_default_callable(self) -> None:
        wizard = Wizard()
        wizard.answers = {"llm.provider": "openai"}
        q = Question(key="test", prompt="Test?", type=QuestionType.TEXT, default=_embedding_default)
        assert wizard._resolve_default(q) == "text-embedding-3-small"

    def test_ask_question_skip(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        wizard.answers = {"infrastructure": {"vector_backend": "null"}}
        q = Question(
            key="infrastructure.embedding_model",
            prompt="Embedding?",
            type=QuestionType.TEXT,
            condition=lambda a: a.get("infrastructure", {}).get("vector_backend") != "null",
        )
        with patch.object(wizard.console, "input", return_value=""):
            result = wizard.ask_question(q)
            assert result is None

    def test_ask_question_bool_yes(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Enable?", type=QuestionType.BOOL, default=False)
        with patch.object(wizard.console, "input", return_value="y"):
            result = wizard.ask_question(q)
            assert result is True

    def test_ask_question_bool_no(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Enable?", type=QuestionType.BOOL, default=True)
        with patch.object(wizard.console, "input", return_value="n"):
            result = wizard.ask_question(q)
            assert result is False

    def test_ask_question_bool_default(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Enable?", type=QuestionType.BOOL, default=True)
        with patch.object(wizard.console, "input", return_value=""):
            result = wizard.ask_question(q)
            assert result is True

    def test_ask_question_number(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Count?", type=QuestionType.NUMBER, default=10)
        with patch.object(wizard.console, "input", return_value="42"):
            result = wizard.ask_question(q)
            assert result == 42

    def test_ask_question_number_default(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Count?", type=QuestionType.NUMBER, default=10)
        with patch.object(wizard.console, "input", return_value=""):
            result = wizard.ask_question(q)
            assert result == 10

    def test_ask_question_text_with_default(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Name?", type=QuestionType.TEXT, default="hello")
        with patch.object(wizard.console, "input", return_value="world"):
            result = wizard.ask_question(q)
            assert result == "world"

    def test_ask_question_text_empty_uses_default(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Name?", type=QuestionType.TEXT, default="hello")
        with patch.object(wizard.console, "input", return_value=""):
            result = wizard.ask_question(q)
            assert result == "hello"

    def test_ask_question_text_back(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Name?", type=QuestionType.TEXT, default="hello")
        with patch.object(wizard.console, "input", return_value="back"):
            result = wizard.ask_question(q)
            assert result == "BACK"

    def test_ask_question_text_skip(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Name?", type=QuestionType.TEXT, default="hello")
        with patch.object(wizard.console, "input", return_value="skip"):
            result = wizard.ask_question(q)
            assert result == "hello"

    def test_ask_question_select(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Pick?", type=QuestionType.SELECT, choices=["a", "b", "c"], default="a")
        with patch.object(wizard.console, "input", return_value="2"):
            result = wizard.ask_question(q)
            assert result == "b"

    def test_ask_question_select_default(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Pick?", type=QuestionType.SELECT, choices=["a", "b"], default="a")
        with patch.object(wizard.console, "input", return_value=""):
            result = wizard.ask_question(q)
            assert result == "a"

    def test_ask_question_select_skip(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Pick?", type=QuestionType.SELECT, choices=["a", "b"], default="a")
        with patch.object(wizard.console, "input", return_value="skip"):
            result = wizard.ask_question(q)
            assert result == "a"

    def test_ask_question_select_back(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Pick?", type=QuestionType.SELECT, choices=["a", "b"], default="a")
        with patch.object(wizard.console, "input", return_value="back"):
            result = wizard.ask_question(q)
            assert result == "BACK"

    def test_ask_question_multi_select(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Pick?", type=QuestionType.MULTI_SELECT, choices=["a", "b", "c"])
        with patch.object(wizard.console, "input", return_value="1,3"):
            result = wizard.ask_question(q)
            assert result == ["a", "c"]

    def test_ask_question_multi_select_empty(self) -> None:
        from rich.console import Console
        from unittest.mock import patch

        wizard = Wizard(console=Console(force_terminal=True))
        q = Question(key="test", prompt="Pick?", type=QuestionType.MULTI_SELECT, choices=["a", "b"])
        with patch.object(wizard.console, "input", return_value=""):
            result = wizard.ask_question(q)
            assert result == []

    def test_run_phase(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        phase = Phase(
            name="Test",
            questions=[
                Question(key="a.b", prompt="B?", type=QuestionType.TEXT, default="hello"),
            ],
        )
        with patch.object(wizard, "ask_question", return_value="world"):
            result = wizard.run_phase(phase, 1, 1)
            assert result is True
            assert wizard.get_nested("a.b") == "world"

    def test_run_phase_skipped(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        wizard.answers = {"skip": True}
        phase = Phase(
            name="Test",
            questions=[Question(key="test", prompt="T?", type=QuestionType.TEXT)],
            condition=lambda a: not a.get("skip"),
        )
        result = wizard.run_phase(phase, 1, 1)
        assert result is True

    def test_run_phase_back(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        phase = Phase(
            name="Test",
            questions=[Question(key="test", prompt="T?", type=QuestionType.TEXT)],
        )
        with patch.object(wizard, "ask_question", return_value="BACK"):
            result = wizard.run_phase(phase, 1, 1)
            assert result is False

    def test_collect_agent(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        inputs = iter(["testagent", "A test agent", "You are test", "", "n", "n", "n", "n", "n"])
        with patch.object(wizard.console, "input", side_effect=lambda *a, **k: next(inputs)):
            with patch("builtins.input", side_effect=["END", "END"]):
                agent = wizard._collect_agent()
                assert agent is not None
                assert agent["name"] == "testagent"
                assert agent["description"] == "A test agent"

    def test_collect_agent_empty_name(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        with patch.object(wizard.console, "input", return_value=""):
            result = wizard._collect_agent()
            assert result is None

    def test_collect_tool(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        inputs = iter(["my_tool", "myproject.tools.my_tool", "A tool", "n"])
        with patch.object(wizard.console, "input", side_effect=lambda *a, **k: next(inputs)):
            tool = wizard._collect_tool()
            assert tool is not None
            assert tool["name"] == "my_tool"

    def test_collect_tool_empty_name(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        with patch.object(wizard.console, "input", return_value=""):
            result = wizard._collect_tool()
            assert result is None

    def test_collect_skill(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        inputs = iter(["my_skill", "A skill", "n"])
        with patch.object(wizard.console, "input", side_effect=lambda *a, **k: next(inputs)):
            skill = wizard._collect_skill()
            assert skill is not None
            assert skill["name"] == "my_skill"

    def test_collect_skill_empty_name(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        with patch.object(wizard.console, "input", return_value=""):
            result = wizard._collect_skill()
            assert result is None

    def test_run_agent_loop(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        with patch.object(wizard.console, "input", return_value="n"):
            wizard._run_agent_loop()
            assert wizard.answers.get("_agents") == []

    def test_run_tools_loop(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        with patch.object(wizard.console, "input", return_value="n"):
            wizard._run_tools_loop()
            assert wizard.answers.get("_tools") == []

    def test_run_skills_loop(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        with patch.object(wizard.console, "input", return_value="n"):
            wizard._run_skills_loop()
            assert wizard.answers.get("_skills") == []

    def test_run_guardrails_skip_input(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        with patch.object(wizard.console, "input", return_value="n"):
            wizard._run_guardrails()
            assert wizard.answers.get("_guardrails", {}).get("input") == []

    def test_run_events_disabled(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        with patch.object(wizard.console, "input", return_value="n"):
            wizard._run_events()
            assert wizard.answers.get("events", {}).get("enabled") is False

    def test_run_mcp_gateway_disabled(self) -> None:
        from rich.console import Console

        wizard = Wizard(console=Console(force_terminal=True))
        with patch.object(wizard.console, "input", return_value="n"):
            wizard._run_mcp_gateway()
            assert wizard.answers.get("_mcp_gateway", {}).get("configure") is False


class TestQuestionsEdgeCases:
    def test_skip_if_null_vector_url_qdrant(self) -> None:
        answers = {"infrastructure": {"vector_backend": "qdrant"}}
        assert _skip_if_null_vector_url(answers) is False

    def test_skip_if_null_vector_url_chroma(self) -> None:
        answers = {"infrastructure": {"vector_backend": "chroma"}}
        assert _skip_if_null_vector_url(answers) is False

    def test_skip_if_null_vector_url_null(self) -> None:
        answers = {"infrastructure": {"vector_backend": "null"}}
        assert _skip_if_null_vector_url(answers) is True

    def test_skip_if_no_tracing_true(self) -> None:
        answers = {"infrastructure.langsmith_tracing": True}
        assert _skip_if_no_tracing(answers) is False

    def test_skip_if_no_tracing_false(self) -> None:
        answers = {"infrastructure.langsmith_tracing": False}
        assert _skip_if_no_tracing(answers) is True

    def test_skip_if_no_startup_hook_set(self) -> None:
        answers = {"infrastructure.startup_hook_path": "myproject.hooks.on_start"}
        assert _skip_if_no_startup_hook(answers) is False

    def test_skip_if_no_startup_hook_empty(self) -> None:
        answers = {"infrastructure.startup_hook_path": ""}
        assert _skip_if_no_startup_hook(answers) is True

    def test_all_phases_defined(self) -> None:
        assert len(ALL_PHASES) == 9

    def test_phase_0_identity_questions(self) -> None:
        assert len(PHASE_0_IDENTITY.questions) == 3

    def test_phase_1_infrastructure_questions(self) -> None:
        assert len(PHASE_1_INFRASTRUCTURE.questions) > 10

    def test_phase_2_supervisor_questions(self) -> None:
        assert len(PHASE_2_SUPERVISOR.questions) > 3


class TestValidatorsEdgeCases:
    def test_validate_path_exists(self, tmp_path: Path) -> None:
        valid, _ = validate_path_exists(str(tmp_path))
        assert valid

    def test_validate_path_exists_missing(self) -> None:
        valid, err = validate_path_exists("/nonexistent/path/xyz")
        assert not valid
        assert "does not exist" in err

    def test_validate_yaml_safe_starts_with_brace(self) -> None:
        valid, err = validate_yaml_safe("{hello")
        assert not valid

    def test_validate_yaml_safe_ends_with_brace(self) -> None:
        valid, err = validate_yaml_safe("hello}")
        assert not valid

    def test_validate_number_range_float(self) -> None:
        valid, _ = validate_number_range("3.14", 0, 10)
        assert valid

    def test_validate_full_config_bad_vector_backend(self) -> None:
        answers = {
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.vector_backend": "invalid",
            "_agents": [{"name": "testagent", "description": "Test", "prompt": "You are test"}],
        }
        valid, errors = validate_full_config(answers)
        assert not valid
        assert any("Invalid vector backend" in e for e in errors)

    def test_validate_full_config_bad_embedding(self) -> None:
        answers = {
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.vector_backend": "qdrant",
            "infrastructure.embedding_model": "badmodel",
            "_agents": [{"name": "testagent", "description": "Test", "prompt": "You are test"}],
        }
        valid, errors = validate_full_config(answers)
        assert not valid
        assert any("provider/model format" in e for e in errors)

    def test_validate_agent_config_missing_prompt(self) -> None:
        config = {"description": "Test"}
        valid, errors = validate_agent_config("testagent", config)
        assert not valid
        assert any("prompt" in e for e in errors)


class TestTemplatesEdgeCases:
    def test_build_orchid_yml_custom_storage(self) -> None:
        answers = {
            "project.name": "testproject",
            "project.description": "A test project",
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.auth_mode": "dev_bypass",
            "infrastructure.vector_backend": "qdrant",
            "infrastructure.qdrant_url": "http://localhost:6333",
            "infrastructure.embedding_model": "ollama/nomic-embed-text",
            "infrastructure.storage_backend": "custom",
            "infrastructure.storage_class": "myproject.storage.MyStorage",
            "infrastructure.storage_dsn": "postgres://localhost/db",
            "infrastructure.vision_model": "ollama/minicpm-v",
            "infrastructure.upload_namespace": "uploads",
            "infrastructure.upload_max_size_mb": 20,
            "infrastructure.chunk_size": 1000,
            "infrastructure.chunk_overlap": 200,
            "infrastructure.checkpointer": "memory",
            "infrastructure.langsmith_tracing": False,
        }
        result = _build_orchid_yml(answers)
        data = yaml.safe_load(result)
        assert data is not None
        assert "MyStorage" in data["storage"]["class"]

    def test_build_orchid_yml_langsmith_enabled(self) -> None:
        answers = {
            "project.name": "testproject",
            "project.description": "A test project",
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.auth_mode": "dev_bypass",
            "infrastructure.vector_backend": "qdrant",
            "infrastructure.qdrant_url": "http://localhost:6333",
            "infrastructure.embedding_model": "ollama/nomic-embed-text",
            "infrastructure.storage_backend": "sqlite",
            "infrastructure.storage_dsn": "~/.orchid/chats.db",
            "infrastructure.vision_model": "ollama/minicpm-v",
            "infrastructure.upload_namespace": "uploads",
            "infrastructure.upload_max_size_mb": 20,
            "infrastructure.chunk_size": 1000,
            "infrastructure.chunk_overlap": 200,
            "infrastructure.checkpointer": "memory",
            "infrastructure.langsmith_tracing": True,
        }
        result = _build_orchid_yml(answers)
        data = yaml.safe_load(result)
        assert data["tracing"]["langsmith_tracing"] is True

    def test_build_orchid_yml_identity_resolver(self) -> None:
        answers = {
            "project.name": "testproject",
            "project.description": "A test project",
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.auth_mode": "custom",
            "infrastructure.identity_resolver_class": "myproject.identity.MyResolver",
            "infrastructure.vector_backend": "qdrant",
            "infrastructure.qdrant_url": "http://localhost:6333",
            "infrastructure.embedding_model": "ollama/nomic-embed-text",
            "infrastructure.storage_backend": "sqlite",
            "infrastructure.storage_dsn": "~/.orchid/chats.db",
            "infrastructure.vision_model": "ollama/minicpm-v",
            "infrastructure.upload_namespace": "uploads",
            "infrastructure.upload_max_size_mb": 20,
            "infrastructure.chunk_size": 1000,
            "infrastructure.chunk_overlap": 200,
            "infrastructure.checkpointer": "memory",
            "infrastructure.langsmith_tracing": False,
        }
        result = _build_orchid_yml(answers)
        data = yaml.safe_load(result)
        assert "identity_resolver_class" in data["auth"]

    def test_build_agents_yaml_with_tools_params(self) -> None:
        answers = {
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.vector_backend": "qdrant",
            "_agents": [],
            "_tools": [
                {
                    "name": "search",
                    "handler": "myproject.tools.search.search_handler",
                    "description": "Search the knowledge base",
                    "parameters": {
                        "query": {"type": "string", "description": "Search query", "required": True},
                        "limit": {"type": "number", "description": "Max results", "required": False},
                    },
                }
            ],
            "_skills": [],
            "_guardrails": {"input": [], "output": []},
            "events": {"enabled": False},
            "_mcp_gateway": {"configure": False},
        }
        result = _build_agents_yaml(answers)
        data = yaml.safe_load(result)
        assert data is not None
        assert "tools" in data
        assert "search" in data["tools"]
        assert "parameters" in data["tools"]["search"]

    def test_build_agents_yaml_with_skills(self) -> None:
        answers = {
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.vector_backend": "qdrant",
            "_agents": [],
            "_tools": [],
            "_skills": [
                {
                    "name": "research",
                    "description": "Research a topic",
                    "steps": [
                        {"agent": "searcher", "instruction": "Search for the topic"},
                        {"agent": "summarizer", "instruction": "Summarize results"},
                    ],
                }
            ],
            "_guardrails": {"input": [], "output": []},
            "events": {"enabled": False},
            "_mcp_gateway": {"configure": False},
        }
        result = _build_agents_yaml(answers)
        data = yaml.safe_load(result)
        assert data is not None
        assert "skills" in data
        assert "research" in data["skills"]

    def test_build_agents_yaml_with_events(self) -> None:
        answers = {
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.vector_backend": "qdrant",
            "_agents": [],
            "_tools": [],
            "_skills": [],
            "_guardrails": {"input": [], "output": []},
            "events": {"enabled": True},
            "_mcp_gateway": {"configure": False},
        }
        result = _build_agents_yaml(answers)
        data = yaml.safe_load(result)
        assert data is not None
        assert "events" in data
        assert data["events"]["enabled"] is True

    def test_build_agents_yaml_with_mcp_gateway(self) -> None:
        answers = {
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.vector_backend": "qdrant",
            "_agents": [],
            "_tools": [],
            "_skills": [],
            "_guardrails": {"input": [], "output": []},
            "events": {"enabled": False},
            "_mcp_gateway": {"configure": True},
        }
        result = _build_agents_yaml(answers)
        data = yaml.safe_load(result)
        assert data is not None
        assert "mcp_gateway" in data

    def test_build_agents_yaml_agent_with_mcp(self) -> None:
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
                    "mcp_servers": [
                        {"name": "myserver", "url": "http://localhost:8080", "auth_mode": "none", "tools": "*"},
                    ],
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
        assert "mcp_servers" in data["agents"]["testagent"]

    def test_build_agents_yaml_agent_with_rag(self) -> None:
        answers = {
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.vector_backend": "qdrant",
            "_agents": [
                {
                    "name": "testagent",
                    "description": "A test agent",
                    "prompt": "You are a test agent",
                    "agent_type": "GenericAgent",
                    "rag_enabled": True,
                    "rag_namespace": "test_ns",
                    "rag_ingestion": "recursive",
                    "rag_retrieval": "hyde",
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
        rag = data["agents"]["testagent"]["rag"]
        assert rag["enabled"] is True
        assert rag["namespace"] == "test_ns"


class TestScaffoldingEdgeCases:
    def test_generate_with_custom_storage(self) -> None:
        answers = {
            "project.name": "testproject",
            "project.description": "A test project",
            "infrastructure.llm_model": "ollama/llama3.2",
            "infrastructure.auth_mode": "dev_bypass",
            "infrastructure.vector_backend": "qdrant",
            "infrastructure.storage_backend": "custom",
            "infrastructure.storage_class": "testproject.storage.MyStorage",
            "infrastructure.storage_dsn": "postgres://localhost/db",
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
        assert "testproject/storage/__init__.py" in files
        assert "testproject/storage/mystorage.py" in files

    def test_generate_with_events(self) -> None:
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
            "_agents": [],
            "_tools": [],
            "_skills": [],
            "_guardrails": {"input": [], "output": []},
            "events": {"enabled": True},
            "_mcp_gateway": {"configure": False},
        }
        scaffold = ScaffoldGenerator(answers, "testproject")
        files = scaffold.generate()
        agents_yaml = yaml.safe_load(files["testproject/agents.yaml"])
        assert agents_yaml["events"]["enabled"] is True


class TestOutputEdgeCases:
    def test_print_success_summary(self) -> None:
        from rich.console import Console
        from orchid_cli.commands._flower.output import print_success_summary

        console = Console(force_terminal=True)
        print_success_summary(Path("/tmp/test.zip"), 10, console=console)

    def test_display_file_tree_nested(self) -> None:
        from rich.console import Console
        from orchid_cli.commands._flower.output import display_file_tree

        file_tree = {
            "testproject/orchid.yml": "content",
            "testproject/agents/__init__.py": "content",
            "testproject/agents/myagent.py": "content",
            "testproject/tools/__init__.py": "content",
            "testproject/tools/mytool.py": "content",
        }
        console = Console(force_terminal=True)
        display_file_tree(file_tree, console=console)


class TestGenerateFlowerCommand:
    def test_command_seed_file_not_found(self) -> None:
        from typer.testing import CliRunner
        from orchid_cli.commands.generate_flower import app

        runner = CliRunner()
        result = runner.invoke(app, ["--from-seed", "/nonexistent/seed.json"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_command_help(self) -> None:
        from typer.testing import CliRunner
        from orchid_cli.commands.generate_flower import app

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "wizard" in result.output.lower()
