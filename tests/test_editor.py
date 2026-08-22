"""Tests for interactive multiline prompt entry."""

import os
import stat
import subprocess
import unittest
from pathlib import Path

from buddy_cli.editor import EditorError, read_prompt_from_editor


class EditorTests(unittest.TestCase):
    def test_visual_editor_receives_secure_file_and_returns_multiline_unicode(
        self,
    ) -> None:
        observed_path = None
        observed_mode = None
        observed_command = None

        def run_editor(command, *, check):
            nonlocal observed_path, observed_mode, observed_command
            self.assertFalse(check)
            observed_command = command
            observed_path = Path(command[-1])
            observed_mode = stat.S_IMODE(observed_path.stat().st_mode)
            with observed_path.open("a", encoding="utf-8") as prompt_file:
                prompt_file.write(
                    'First line with "quotes"\nSecond line: こんにちは 👋\n'
                )
            return subprocess.CompletedProcess(command, 0)

        result = read_prompt_from_editor(
            environment={"VISUAL": "code --wait", "EDITOR": "nano"},
            find_executable=lambda command: f"/tools/{command}",
            run_editor=run_editor,
        )

        self.assertEqual(
            result,
            'First line with "quotes"\nSecond line: こんにちは 👋',
        )
        self.assertEqual(observed_command[:2], ["/tools/code", "--wait"])
        self.assertEqual(observed_mode, stat.S_IRUSR | stat.S_IWUSR)
        self.assertFalse(observed_path.exists())

    def test_editor_environment_variable_precedence_and_fallback(self) -> None:
        commands = []

        def find_executable(command):
            return "/usr/bin/vi" if command == "vi" else None

        def run_editor(command, *, check):
            commands.append(command)
            with Path(command[-1]).open("a", encoding="utf-8") as prompt_file:
                prompt_file.write("Fallback prompt")
            return subprocess.CompletedProcess(command, 0)

        result = read_prompt_from_editor(
            environment={"VISUAL": "missing-visual", "EDITOR": "missing-editor"},
            platform_name="linux",
            find_executable=find_executable,
            run_editor=run_editor,
        )

        self.assertEqual(result, "Fallback prompt")
        self.assertEqual(commands[0][0], "/usr/bin/vi")

    def test_windows_uses_notepad_fallback(self) -> None:
        commands = []

        def run_editor(command, *, check):
            commands.append(command)
            with Path(command[-1]).open("a", encoding="utf-8") as prompt_file:
                prompt_file.write("Windows prompt")
            return subprocess.CompletedProcess(command, 0)

        result = read_prompt_from_editor(
            environment={},
            platform_name="win32",
            find_executable=lambda command: r"C:\Windows\notepad.exe",
            run_editor=run_editor,
        )

        self.assertEqual(result, "Windows prompt")
        self.assertEqual(commands[0][0], r"C:\Windows\notepad.exe")

    def test_reports_when_no_editor_is_available(self) -> None:
        with self.assertRaisesRegex(EditorError, "no text editor is available"):
            read_prompt_from_editor(
                environment={},
                platform_name="linux",
                find_executable=lambda command: None,
            )

    def test_reports_unsuccessful_editor_exit_and_removes_file(self) -> None:
        prompt_path = None

        def run_editor(command, *, check):
            nonlocal prompt_path
            prompt_path = Path(command[-1])
            return subprocess.CompletedProcess(command, 17)

        with self.assertRaisesRegex(EditorError, "exit code 17"):
            read_prompt_from_editor(
                environment={"EDITOR": "editor"},
                find_executable=lambda command: "/tools/editor",
                run_editor=run_editor,
            )

        self.assertFalse(prompt_path.exists())

    def test_reports_editor_closed_without_saving(self) -> None:
        def run_editor(command, *, check):
            return subprocess.CompletedProcess(command, 0)

        with self.assertRaisesRegex(EditorError, "without saving"):
            read_prompt_from_editor(
                environment={"EDITOR": "editor"},
                find_executable=lambda command: "/tools/editor",
                run_editor=run_editor,
            )

    def test_reports_saved_empty_prompt(self) -> None:
        def run_editor(command, *, check):
            Path(command[-1]).write_text("\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)

        with self.assertRaisesRegex(EditorError, "saved an empty prompt"):
            read_prompt_from_editor(
                environment={"EDITOR": "editor"},
                find_executable=lambda command: "/tools/editor",
                run_editor=run_editor,
            )

    def test_reports_guidance_only_file_that_was_explicitly_saved_as_empty(
        self,
    ) -> None:
        def run_editor(command, *, check):
            prompt_path = Path(command[-1])
            initial_stat = prompt_path.stat()
            os.utime(
                prompt_path,
                ns=(initial_stat.st_atime_ns, initial_stat.st_mtime_ns + 1_000_000),
            )
            return subprocess.CompletedProcess(command, 0)

        with self.assertRaisesRegex(EditorError, "saved an empty prompt"):
            read_prompt_from_editor(
                environment={"EDITOR": "editor"},
                find_executable=lambda command: "/tools/editor",
                run_editor=run_editor,
            )

    def test_reports_editor_start_failure(self) -> None:
        def run_editor(command, *, check):
            raise OSError("cannot execute")

        with self.assertRaisesRegex(EditorError, "could not start"):
            read_prompt_from_editor(
                environment={"EDITOR": "editor"},
                find_executable=lambda command: "/tools/editor",
                run_editor=run_editor,
            )


if __name__ == "__main__":
    unittest.main()
