"""Tests for the Buddy command-line interface."""

import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from buddy_cli.cli import main
from buddy_cli.config import BuddyConfig
from buddy_cli.doctor import DiagnosticCheck, DiagnosticReport
from buddy_cli.editor import EditorError
from buddy_cli.updater import (
    ReleaseAsset,
    UpdateError,
    UpdateInfo,
    UpdateOutcome,
)


class StubInput(io.StringIO):
    """String input stream with a configurable terminal state."""

    def __init__(self, value: str, *, is_tty: bool = False) -> None:
        super().__init__(value)
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def available_update(
    *,
    current_version: str = "0.3.4",
    latest_version: str = "0.3.5",
) -> UpdateInfo:
    package = "buddy-linux-x64.tar.gz"
    base_url = (
        f"https://github.com/sarankars/buddy_cli/releases/download/v{latest_version}/"
    )
    return UpdateInfo(
        current_version=current_version,
        latest_version=latest_version,
        release_url=(
            f"https://github.com/sarankars/buddy_cli/releases/tag/v{latest_version}"
        ),
        package=ReleaseAsset(package, f"{base_url}{package}", 100),
        checksum=ReleaseAsset(
            f"{package}.sha256",
            f"{base_url}{package}.sha256",
            90,
        ),
        archive_type="tgz",
    )


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

    def test_enhance_preserves_quotes_newlines_and_unicode_in_an_argument(self) -> None:
        stdout = io.StringIO()
        prompt = 'He said "hello".\nReply with こんにちは 👋'

        exit_code = main(
            ["enhance", "--offline", prompt],
            output_stream=stdout,
            services=object(),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn(f"Request:\n{prompt}", stdout.getvalue())

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

    def test_enhance_opens_editor_for_interactive_multiline_input(self) -> None:
        stdout = io.StringIO()

        with patch(
            "buddy_cli.cli.read_prompt_from_editor",
            return_value='First line with "quotes"\nSecond line: こんにちは 👋',
        ) as open_editor:
            exit_code = main(
                ["enhance", "--offline"],
                input_stream=StubInput("", is_tty=True),
                output_stream=stdout,
                services=object(),
            )

        self.assertEqual(exit_code, 0)
        open_editor.assert_called_once_with()
        self.assertIn(
            'Request:\nFirst line with "quotes"\nSecond line: こんにちは 👋',
            stdout.getvalue(),
        )

    def test_enhance_reports_editor_error(self) -> None:
        stderr = io.StringIO()

        with patch(
            "buddy_cli.cli.read_prompt_from_editor",
            side_effect=EditorError("the editor closed without saving a prompt"),
        ):
            exit_code = main(
                ["enhance"],
                input_stream=StubInput("", is_tty=True),
                error_stream=stderr,
                services=object(),
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("without saving", stderr.getvalue())

    def test_enhance_does_not_open_editor_for_arguments_or_piped_input(self) -> None:
        with patch("buddy_cli.cli.read_prompt_from_editor") as open_editor:
            direct_exit_code = main(
                ["enhance", "--offline", "direct prompt"],
                output_stream=io.StringIO(),
                services=object(),
            )
            piped_exit_code = main(
                ["enhance", "--offline"],
                input_stream=StubInput("piped prompt"),
                output_stream=io.StringIO(),
                services=object(),
            )

        self.assertEqual((direct_exit_code, piped_exit_code), (0, 0))
        open_editor.assert_not_called()

    def test_enhance_reports_empty_piped_prompt(self) -> None:
        stderr = io.StringIO()

        exit_code = main(
            ["enhance", "--offline"],
            input_stream=StubInput(" \n"),
            error_stream=stderr,
            services=object(),
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("prompt cannot be empty", stderr.getvalue())

    def test_enhance_help_describes_editor_and_piped_input(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout), self.assertRaises(SystemExit) as exit_context:
            main(["enhance", "--help"])

        self.assertEqual(exit_context.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("VISUAL/EDITOR", help_text)
        self.assertIn("piped standard", help_text)
        self.assertIn("input or opens a text editor", help_text)

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

    def test_update_check_reports_an_available_release_without_installing(self) -> None:
        stdout = io.StringIO()
        updater = MagicMock()
        updater.check.return_value = available_update()

        exit_code = main(
            ["update", "--check"],
            output_stream=stdout,
            services=SimpleNamespace(updater=updater),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("0.3.5 is available", stdout.getvalue())
        self.assertIn("releases/tag/v0.3.5", stdout.getvalue())
        updater.install.assert_not_called()

    def test_update_reports_when_buddy_is_up_to_date(self) -> None:
        stdout = io.StringIO()
        updater = MagicMock()
        updater.check.return_value = available_update(latest_version="0.3.4")

        exit_code = main(
            ["update"],
            output_stream=stdout,
            services=SimpleNamespace(updater=updater),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Buddy 0.3.4 is up to date", stdout.getvalue())
        updater.install.assert_not_called()

    def test_update_yes_installs_without_interactive_confirmation(self) -> None:
        stdout = io.StringIO()
        updater = MagicMock()
        updater.check.return_value = available_update()
        updater.install.return_value = UpdateOutcome(
            "Buddy was updated to 0.3.5.",
            restart_required=True,
        )

        exit_code = main(
            ["update", "--yes"],
            input_stream=StubInput(""),
            output_stream=stdout,
            services=SimpleNamespace(updater=updater),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Buddy was updated to 0.3.5", stdout.getvalue())
        updater.install.assert_called_once()
        self.assertIn("progress", updater.install.call_args.kwargs)

    def test_update_requires_confirmation_for_noninteractive_install(self) -> None:
        stderr = io.StringIO()
        updater = MagicMock()
        updater.check.return_value = available_update()

        exit_code = main(
            ["update"],
            input_stream=StubInput(""),
            output_stream=io.StringIO(),
            error_stream=stderr,
            services=SimpleNamespace(updater=updater),
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("buddy update --yes", stderr.getvalue())
        updater.install.assert_not_called()

    def test_update_installs_after_interactive_confirmation(self) -> None:
        stdout = io.StringIO()
        updater = MagicMock()
        updater.check.return_value = available_update()
        updater.install.return_value = UpdateOutcome("Update installed")

        exit_code = main(
            ["update"],
            input_stream=StubInput("yes\n", is_tty=True),
            output_stream=stdout,
            services=SimpleNamespace(updater=updater),
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("Install Buddy 0.3.5?", stdout.getvalue())
        updater.install.assert_called_once()

    def test_update_reports_check_and_install_failures(self) -> None:
        for failure_at in ("check", "install"):
            with self.subTest(failure_at=failure_at):
                stderr = io.StringIO()
                updater = MagicMock()
                updater.check.return_value = available_update()
                if failure_at == "check":
                    updater.check.side_effect = UpdateError("network unavailable")
                    arguments = ["update", "--check"]
                else:
                    updater.install.side_effect = UpdateError("signature invalid")
                    arguments = ["update", "--yes"]

                exit_code = main(
                    arguments,
                    input_stream=StubInput(""),
                    output_stream=io.StringIO(),
                    error_stream=stderr,
                    services=SimpleNamespace(updater=updater),
                )

                self.assertEqual(exit_code, 1)
                self.assertIn("failed", stderr.getvalue())

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
        client.generate.return_value = json.dumps(
            {
                "rewritten_prompt": "Improve README installation instructions.",
            }
        )

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

    def test_enhance_never_prints_rejected_model_output(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        config = BuddyConfig(
            provider="system",
            base_url="http://127.0.0.1:11434",
            model="test-model",
        )
        services = SimpleNamespace(
            config_store=MagicMock(load=lambda: config),
            runtime_manager=MagicMock(),
        )
        unsafe_answer = "The answer is 4."
        client = MagicMock()
        client.generate.return_value = json.dumps({"rewritten_prompt": unsafe_answer})

        with patch("buddy_cli.cli.OllamaClient", return_value=client):
            exit_code = main(
                ["enhance", "What", "is", "2+2?"],
                output_stream=stdout,
                error_stream=stderr,
                services=services,
            )

        self.assertEqual(exit_code, 0)
        self.assertNotIn(unsafe_answer, stdout.getvalue())
        self.assertIn("Request:\nWhat is 2+2?", stdout.getvalue())
        self.assertIn("using offline enhancer", stderr.getvalue())
        self.assertEqual(client.generate.call_count, 2)


if __name__ == "__main__":
    unittest.main()
