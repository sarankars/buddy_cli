"""Build a platform-specific standalone Buddy executable with PyInstaller."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence


def build_command(
    project_root: Path,
    codesign_identity: Optional[str] = None,
) -> list[str]:
    """Return the PyInstaller command for this platform build."""
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
    ]
    if codesign_identity:
        command.extend(["--codesign-identity", codesign_identity])
    command.append(str(project_root / "src" / "buddy_cli" / "__main__.py"))
    return command


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--codesign-identity",
        help="Developer ID Application identity used for macOS builds",
    )
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    command = build_command(project_root, args.codesign_identity)
    completed = subprocess.run(command, cwd=project_root, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
