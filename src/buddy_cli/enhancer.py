"""Prompt enhancement strategies."""

from __future__ import annotations

from dataclasses import dataclass


class EmptyPromptError(ValueError):
    """Raised when an empty prompt cannot be enhanced."""


@dataclass(frozen=True)
class RuleBasedEnhancer:
    """Create a clearer request wrapper without calling an external model."""

    preamble: str = (
        "Please carry out the request below. Preserve the original intent, ask "
        "for clarification only when a missing detail would materially change "
        "the result, state any reasonable assumptions, and make the result clear "
        "and actionable."
    )

    def enhance(self, prompt: str) -> str:
        """Return a deterministic enhanced prompt."""
        cleaned_prompt = prompt.strip()
        if not cleaned_prompt:
            raise EmptyPromptError("the prompt cannot be empty")

        return f"{self.preamble}\n\nRequest:\n{cleaned_prompt}"
