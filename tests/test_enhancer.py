"""Tests for prompt enhancement strategies."""

import unittest

from buddy_cli.enhancer import EmptyPromptError, OllamaEnhancer, RuleBasedEnhancer


class RuleBasedEnhancerTests(unittest.TestCase):
    def test_enhance_preserves_the_original_request(self) -> None:
        result = RuleBasedEnhancer().enhance("  make the readme better  ")

        self.assertTrue(result.endswith("Request:\nmake the readme better"))

    def test_enhance_rejects_an_empty_prompt(self) -> None:
        with self.assertRaises(EmptyPromptError):
            RuleBasedEnhancer().enhance("   \n")


class FakeOllamaClient:
    def __init__(self) -> None:
        self.request = None

    def generate(self, model: str, prompt: str, *, system: str) -> str:
        self.request = (model, prompt, system)
        return "Improve README.md with installation and usage examples."


class OllamaEnhancerTests(unittest.TestCase):
    def test_enhance_uses_the_configured_local_model(self) -> None:
        client = FakeOllamaClient()

        result = OllamaEnhancer(client, "test-model").enhance("  improve docs  ")

        self.assertEqual(
            result,
            "Improve README.md with installation and usage examples.",
        )
        self.assertEqual(client.request[0:2], ("test-model", "improve docs"))

    def test_enhance_rejects_empty_input_before_calling_ollama(self) -> None:
        with self.assertRaises(EmptyPromptError):
            OllamaEnhancer(FakeOllamaClient(), "test-model").enhance(" \n ")


if __name__ == "__main__":
    unittest.main()
