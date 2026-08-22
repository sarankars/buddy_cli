"""Tests for prompt enhancement strategies."""

import unittest

from buddy_cli.enhancer import EmptyPromptError, RuleBasedEnhancer


class RuleBasedEnhancerTests(unittest.TestCase):
    def test_enhance_preserves_the_original_request(self) -> None:
        result = RuleBasedEnhancer().enhance("  make the readme better  ")

        self.assertTrue(result.endswith("Request:\nmake the readme better"))

    def test_enhance_rejects_an_empty_prompt(self) -> None:
        with self.assertRaises(EmptyPromptError):
            RuleBasedEnhancer().enhance("   \n")


if __name__ == "__main__":
    unittest.main()
