"""Interactive multiline prompt entry through the user's text editor."""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence


class EditorError(RuntimeError):
    """Raised when interactive prompt entry cannot be completed."""


_PROMPT_MARKER = "# --- Enter your prompt below this line ---\n"
_EDITOR_GUIDANCE = (
    "# Buddy multiline prompt editor\n"
    "# Write or paste your rough prompt below. Save and close the editor when done.\n"
    "# These guidance lines are not included in the prompt.\n"
    f"{_PROMPT_MARKER}"
)


def _editor_candidates(environment: Mapping[str, str], platform_name: str) -> list[str]:
    candidates = []
    for variable in ("VISUAL", "EDITOR"):
        configured = environment.get(variable, "").strip()
        if configured and configured not in candidates:
            candidates.append(configured)

    fallbacks = ["notepad"] if platform_name.startswith("win") else ["vim", "vi"]
    candidates.extend(
        candidate for candidate in fallbacks if candidate not in candidates
    )
    return candidates


def _resolve_editor(
    environment: Mapping[str, str],
    platform_name: str,
    find_executable: Callable[[str], Optional[str]],
) -> Sequence[str]:
    attempted = []
    for candidate in _editor_candidates(environment, platform_name):
        try:
            command = shlex.split(candidate, posix=not platform_name.startswith("win"))
        except ValueError:
            attempted.append(candidate)
            continue
        if not command:
            continue
        if platform_name.startswith("win"):
            command = [part.strip('"') for part in command]
        attempted.append(command[0])
        executable = find_executable(command[0])
        if executable:
            return [executable, *command[1:]]

    tried = ", ".join(attempted) if attempted else "no editor commands"
    raise EditorError(
        "no text editor is available "
        f"(tried {tried}); set VISUAL or EDITOR to an installed editor"
    )


def _extract_prompt(contents: str, initial_contents: str, *, was_saved: bool) -> str:
    if contents == initial_contents and not was_saved:
        raise EditorError("the editor closed without saving a prompt")

    if _PROMPT_MARKER in contents:
        contents = contents.split(_PROMPT_MARKER, 1)[1]
    prompt = contents.strip()
    if not prompt:
        raise EditorError("the editor saved an empty prompt")
    return prompt


def read_prompt_from_editor(
    *,
    environment: Optional[Mapping[str, str]] = None,
    platform_name: Optional[str] = None,
    find_executable: Callable[[str], Optional[str]] = shutil.which,
    run_editor: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> str:
    """Open a secure temporary file and return the prompt saved by the user."""
    active_environment = os.environ if environment is None else environment
    active_platform = sys.platform if platform_name is None else platform_name
    command = _resolve_editor(
        active_environment,
        active_platform,
        find_executable,
    )

    descriptor, raw_path = tempfile.mkstemp(prefix="buddy-prompt-", suffix=".txt")
    prompt_path = Path(raw_path)
    initial_contents = _EDITOR_GUIDANCE
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as prompt_file:
            os.chmod(prompt_path, stat.S_IRUSR | stat.S_IWUSR)
            prompt_file.write(initial_contents)
            prompt_file.flush()
        initial_modified_time = prompt_path.stat().st_mtime_ns

        try:
            completed = run_editor([*command, str(prompt_path)], check=False)
        except OSError as exc:
            raise EditorError(f"could not start the text editor: {exc}") from exc
        if completed.returncode != 0:
            raise EditorError(
                f"the text editor exited unsuccessfully (exit code {completed.returncode})"
            )

        try:
            contents = prompt_path.read_text(encoding="utf-8")
            was_saved = prompt_path.stat().st_mtime_ns != initial_modified_time
        except OSError as exc:
            raise EditorError(
                f"could not read the prompt from the editor: {exc}"
            ) from exc
        return _extract_prompt(contents, initial_contents, was_saved=was_saved)
    finally:
        with suppress(OSError):
            prompt_path.unlink(missing_ok=True)
