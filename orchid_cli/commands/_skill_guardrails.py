"""Guardrail-section rendering for SKILL.md files.

Combines the global guardrail chain with the per-agent override into the
``## Guardrails`` block consumed by Claude Code skills.
"""

from __future__ import annotations

from orchid_ai.config.schema import OrchidGuardrailRuleConfig, OrchidGuardrailsConfig


def build_guardrails_section(
    global_guardrails: OrchidGuardrailsConfig,
    agent_guardrails: OrchidGuardrailsConfig | None,
    agent_name: str | None,
) -> str:
    """Build the ``## Guardrails`` section for a SKILL.md file.

    Combines global guardrails (applied to all agents) with per-agent
    guardrails into human-readable enforcement rules.

    Returns an empty string if no guardrails are configured.
    """
    has_global = global_guardrails.input or global_guardrails.output
    has_agent = agent_guardrails is not None and (agent_guardrails.input or agent_guardrails.output)

    if not has_global and not has_agent:
        return ""

    parts: list[str] = []
    parts.append("## Guardrails\n")
    parts.append(
        "The following safety rules are enforced in the Orchid runtime. "
        "When operating as this skill, you MUST respect these constraints.\n"
    )

    input_rules: list[OrchidGuardrailRuleConfig] = list(global_guardrails.input)
    output_rules: list[OrchidGuardrailRuleConfig] = list(global_guardrails.output)

    if agent_guardrails is not None:
        input_rules.extend(agent_guardrails.input)
        output_rules.extend(agent_guardrails.output)

    if input_rules:
        parts.append("### Input Rules\n")
        parts.append("These rules apply to user messages BEFORE processing:\n")
        for rule in input_rules:
            parts.append(_format_rule(rule))
        parts.append("")

    if output_rules:
        parts.append("### Output Rules\n")
        parts.append("These rules apply to responses BEFORE returning to the user:\n")
        for rule in output_rules:
            parts.append(_format_rule(rule))
        parts.append("")

    return "\n".join(parts)


_ACTION_LABELS: dict[str, str] = {
    "block": "**Block** the message",
    "warn": "**Warn** but allow",
    "redact": "**Redact** matched content",
    "log": "**Log** silently",
}

_TYPE_DESCRIPTIONS: dict[str, str] = {
    "prompt_injection": "Prompt injection attempts (instruction overrides, persona hijacks, delimiter injection)",
    "content_safety": "Harmful or unsafe content (violence, self-harm, illegal activity)",
    "pii_detection": "Personally identifiable information (PII)",
    "max_length": "Messages exceeding the character limit",
    "topic_restriction": "Off-topic messages outside allowed domains",
    "groundedness": "Responses not grounded in retrieved context",
}


def _format_rule(rule: OrchidGuardrailRuleConfig) -> str:
    """Format a single guardrail rule as a readable bullet point."""
    action_desc = _ACTION_LABELS.get(rule.fail_action, f"**{rule.fail_action}**")
    type_desc = _TYPE_DESCRIPTIONS.get(rule.type, f"`{rule.type}` guardrail")

    line = f"- **{rule.type}** — {action_desc} if detected: {type_desc}"

    config_details = _format_config(rule.type, rule.config)
    if config_details:
        line += f"\n  {config_details}"

    return line


def _format_config(guardrail_type: str, config: dict) -> str:
    """Format guardrail config dict as a readable detail string."""
    if not config:
        return ""

    details: list[str] = []

    if guardrail_type == "pii_detection" and "entities" in config:
        details.append(f"Entities: {', '.join(config['entities'])}")
    if guardrail_type == "max_length" and "max_characters" in config:
        details.append(f"Max characters: {config['max_characters']}")
    if guardrail_type == "topic_restriction" and "allowed_topics" in config:
        details.append(f"Allowed topics: {', '.join(config['allowed_topics'])}")
    if guardrail_type == "content_safety":
        if "categories" in config:
            details.append(f"Categories: {', '.join(config['categories'])}")
        if "blocklist" in config:
            details.append(f"Blocked words: {', '.join(config['blocklist'])}")
    if guardrail_type == "groundedness" and "min_overlap" in config:
        details.append(f"Min overlap: {config['min_overlap']}")

    return "; ".join(details)
