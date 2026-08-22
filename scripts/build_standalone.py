"""Build a platform-specific standalone Buddy executable with PyInstaller."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name",
        "buddy",
        "--specpath",
        str(project_root / "build"),
        "--paths",
        str(project_root / "src"),
        str(project_root / "src" / "buddy_cli" / "__main__.py"),
    ]
    completed = subprocess.run(command, cwd=project_root, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
