"""Tiny string helpers shared across skill-generation modules."""

from __future__ import annotations


def clean_description(text: str) -> str:
    """Collapse whitespace in a YAML multi-line description."""
    return " ".join(text.split()).strip()


def truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if needed, escaping quotes for YAML."""
    text = text.replace('"', '\\"')
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"
