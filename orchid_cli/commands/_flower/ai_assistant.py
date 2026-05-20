from __future__ import annotations

from typing import Any

from .questions import Question


class AIAssistant:
    def __init__(self, model: str = "ollama/llama3.2") -> None:
        self.model = model

    def explain_option(self, question: Question) -> str:
        prompt = (
            f"Explain what this configuration option means in the context of an AI agent framework. "
            f"Be concise (2-3 sentences).\n\n"
            f"Question: {question.prompt}\n"
            f"Type: {question.type.value}\n"
        )
        if question.choices:
            prompt += f"Choices: {', '.join(question.choices)}\n"
        if question.help_text:
            prompt += f"Hint: {question.help_text}\n"
        try:
            return self._complete(prompt)
        except Exception:
            return "AI explanation unavailable."

    def suggest_value(self, question: Question, context: dict[str, Any]) -> str:
        prompt = (
            f"Suggest a good value for this configuration option. "
            f"Return ONLY the suggested value, nothing else.\n\n"
            f"Question: {question.prompt}\n"
            f"Type: {question.type.value}\n"
        )
        if question.choices:
            prompt += f"Choices: {', '.join(question.choices)}\n"
        if question.default is not None:
            prompt += f"Default: {question.default}\n"
        prompt += "\nContext from prior answers:\n"
        for key, value in list(context.items())[:10]:
            prompt += f"  {key}: {value}\n"
        try:
            return self._complete(prompt).strip()
        except Exception:
            return str(question.default) if question.default is not None else ""

    def validate_choice(self, value: Any, question: Question) -> tuple[bool, str]:
        prompt = (
            f"Is this a good configuration value for an AI agent framework? "
            f"Reply with 'YES' or 'NO: reason' in one line.\n\n"
            f"Question: {question.prompt}\n"
            f"Value: {value}\n"
        )
        if question.choices:
            prompt += f"Valid choices: {', '.join(question.choices)}\n"
        try:
            result = self._complete(prompt).strip()
            if result.upper().startswith("YES"):
                return True, ""
            return False, result
        except Exception:
            return True, ""

    def _complete(self, prompt: str) -> str:
        import litellm

        response = litellm.completion(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=256,
        )
        content = response.choices[0].message.content
        return content if content else ""
