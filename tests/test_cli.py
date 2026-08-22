"""Tests for the Buddy command-line interface."""

import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from buddy_cli.cli import main
from buddy_cli.config import BuddyConfig
from buddy_cli.doctor import DiagnosticCheck, DiagnosticReport


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
            ["enhance", "--offline", "make", "the", "readme", "better"],
            output_stream=stdout,
            services=object(),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Request:\nmake the readme better", stdout.getvalue())

    def test_enhance_reads_from_standard_input(self) -> None:
        stdout = io.StringIO()

        exit_code = main(
            ["enhance", "--offline"],
            input_stream=StubInput("explain this code"),
            output_stream=stdout,
            services=object(),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Request:\nexplain this code", stdout.getvalue())

    def test_enhance_reports_missing_prompt(self) -> None:
        stderr = io.StringIO()

        exit_code = main(
            ["enhance"],
            input_stream=StubInput("", is_tty=True),
            error_stream=stderr,
            services=object(),
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("provide a prompt", stderr.getvalue())

    def test_setup_dry_run_prints_plan(self) -> None:
        stdout = io.StringIO()
        provisioner = MagicMock()
        provisioner.plan.return_value = ["Download runtime", "Download model"]
        services = SimpleNamespace(provisioner=provisioner)

        exit_code = main(
            ["setup", "--dry-run"],
            output_stream=stdout,
            services=services,
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Download runtime", stdout.getvalue())

    def test_setup_yes_completes_without_interactive_input(self) -> None:
        stdout = io.StringIO()
        provisioner = MagicMock()
        services = SimpleNamespace(provisioner=provisioner)

        exit_code = main(
            ["setup", "--yes"],
            input_stream=StubInput(""),
            output_stream=stdout,
            services=services,
        )

        self.assertEqual(exit_code, 0)
        provisioner.setup.assert_called_once()
        self.assertIn("Buddy is ready", stdout.getvalue())

    def test_doctor_json_returns_machine_readable_report(self) -> None:
        stdout = io.StringIO()
        report = DiagnosticReport([DiagnosticCheck("PASS", "api", "Ollama is running")])
        services = SimpleNamespace(doctor=MagicMock(run=lambda: report))

        exit_code = main(
            ["doctor", "--json"],
            output_stream=stdout,
            services=services,
        )

        self.assertEqual(exit_code, 0)
        self.assertTrue(json.loads(stdout.getvalue())["healthy"])

    def test_enhance_uses_configured_ollama(self) -> None:
        stdout = io.StringIO()
        config = BuddyConfig(
            provider="system",
            base_url="http://127.0.0.1:11434",
            model="test-model",
        )
        config_store = MagicMock()
        config_store.load.return_value = config
        runtime_manager = MagicMock()
        services = SimpleNamespace(
            config_store=config_store,
            runtime_manager=runtime_manager,
        )
        client = MagicMock()
        client.generate.return_value = "Improve README installation instructions."

        with patch("buddy_cli.cli.OllamaClient", return_value=client):
            exit_code = main(
                ["enhance", "improve", "readme"],
                output_stream=stdout,
                services=services,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            stdout.getvalue().strip(),
            "Improve README installation instructions.",
        )


if __name__ == "__main__":
    unittest.main()
