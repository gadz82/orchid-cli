from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def validate_dotted_path(value: str) -> tuple[bool, str]:
    if not value:
        return False, "Dotted path cannot be empty"
    pattern = r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+$"
    if not re.match(pattern, value):
        return False, f"Invalid Python dotted path: {value}. Expected format: module.submodule.ClassName"
    return True, ""


def validate_url(value: str) -> tuple[bool, str]:
    if not value:
        return False, "URL cannot be empty"
    pattern = r"^https?://[^\s/$.?#].[^\s]*$"
    if not re.match(pattern, value):
        return False, f"Invalid URL: {value}"
    return True, ""


def validate_model(value: str) -> tuple[bool, str]:
    if not value:
        return False, "Model cannot be empty"
    if "/" not in value:
        return False, f"Model must be in provider/model format (e.g., openai/gpt-4o), got: {value}"
    return True, ""


def validate_agent_name(value: str) -> tuple[bool, str]:
    if not value:
        return False, "Agent name cannot be empty"
    if not re.match(r"^[a-z]+$", value):
        return False, f"Agent name must be lowercase letters only (no underscores, spaces, or numbers): {value}"
    return True, ""


def validate_yaml_safe(value: str) -> tuple[bool, str]:
    unsafe_chars = ["{", "}", "[", "]", ",", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`"]
    for char in unsafe_chars:
        if value.startswith(char) or value.endswith(char):
            return False, f"Value should not start or end with YAML-special character: {char}"
    return True, ""


def validate_number_range(value: str, min_val: int | float, max_val: int | float) -> tuple[bool, str]:
    try:
        num = int(value) if "." not in value else float(value)
    except ValueError:
        return False, f"Invalid number: {value}"
    if num < min_val or num > max_val:
        return False, f"Value must be between {min_val} and {max_val}"
    return True, ""


def validate_required(value: str) -> tuple[bool, str]:
    if not value.strip():
        return False, "This field is required"
    return True, ""


def validate_path_exists(value: str) -> tuple[bool, str]:
    path = Path(value).expanduser()
    if not path.exists():
        return False, f"Path does not exist: {path}"
    return True, ""


def validate_path_writable(value: str) -> tuple[bool, str]:
    path = Path(value).expanduser()
    parent = path.parent if path.suffix else path
    parent.mkdir(parents=True, exist_ok=True)
    if not parent.is_dir():
        return False, f"Cannot create directory: {parent}"
    return True, ""


def validate_full_config(answers: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []

    llm_model = answers.get("infrastructure.llm_model", "")
    if llm_model and "/" not in llm_model:
        errors.append(f"LLM model must be in provider/model format: {llm_model}")

    vector_backend = answers.get("infrastructure.vector_backend", "qdrant")
    if vector_backend not in ("qdrant", "null", "chroma"):
        errors.append(f"Invalid vector backend: {vector_backend}")

    embedding = answers.get("infrastructure.embedding_model", "")
    if vector_backend != "null" and embedding and "/" not in embedding:
        errors.append(f"Embedding model must be in provider/model format: {embedding}")

    agents = answers.get("_agents", [])
    for agent in agents:
        name = agent.get("name", "")
        valid, err = validate_agent_name(name)
        if not valid:
            errors.append(f"Agent: {err}")

    if not agents:
        errors.append("At least one agent must be defined")

    return len(errors) == 0, errors


def validate_agent_config(agent_name: str, config: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []

    valid, err = validate_agent_name(agent_name)
    if not valid:
        errors.append(err)

    if not config.get("description"):
        errors.append("Agent must have a description for supervisor routing")

    if not config.get("prompt"):
        errors.append("Agent must have a system prompt")

    class_path = config.get("class_path", "")
    if class_path:
        valid, err = validate_dotted_path(class_path)
        if not valid:
            errors.append(f"Custom agent class path: {err}")

    return len(errors) == 0, errors
