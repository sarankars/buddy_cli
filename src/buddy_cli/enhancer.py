"""Prompt enhancement strategies."""

from __future__ import annotations

from dataclasses import dataclass

from buddy_cli.ollama import OllamaClient


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


@dataclass(frozen=True)
class OllamaEnhancer:
    """Use a local Ollama model to rewrite a rough prompt."""

    client: OllamaClient
    model: str
    system_prompt: str = (
        "You are a prompt editor. Rewrite the user's rough prompt into a clear, "
        "specific, actionable prompt for another AI assistant. Preserve the "
        "user's intent and constraints. Do not answer the request. Do not invent "
        "facts or requirements. Return only the enhanced prompt, without "
        "commentary, labels, or Markdown fences."
    )

    def enhance(self, prompt: str) -> str:
        cleaned_prompt = prompt.strip()
        if not cleaned_prompt:
            raise EmptyPromptError("the prompt cannot be empty")
        return self.client.generate(
            self.model,
            cleaned_prompt,
            system=self.system_prompt,
        )
