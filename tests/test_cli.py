"""Tests for the Buddy command-line interface."""

import io
import unittest

from buddy_cli.cli import main


class StubInput(io.StringIO):
    """String input stream with a configurable terminal state."""

    def __init__(self, value: str, *, is_tty: bool = False) -> None:
        super().__init__(value)
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


class CliTests(unittest.TestCase):
    def test_enhance_accepts_prompt_arguments(self) -> None:
        stdout = io.StringIO()

        exit_code = main(
            ["enhance", "make", "the", "readme", "better"],
            output_stream=stdout,
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Request:\nmake the readme better", stdout.getvalue())

    def test_enhance_reads_from_standard_input(self) -> None:
        stdout = io.StringIO()

        exit_code = main(
            ["enhance"],
            input_stream=StubInput("explain this code"),
            output_stream=stdout,
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Request:\nexplain this code", stdout.getvalue())

    def test_enhance_reports_missing_prompt(self) -> None:
        stderr = io.StringIO()

        exit_code = main(
            ["enhance"],
            input_stream=StubInput("", is_tty=True),
            error_stream=stderr,
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("provide a prompt", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
