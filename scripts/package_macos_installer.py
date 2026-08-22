"""Create a signed macOS installer package for the Buddy executable."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Sequence

PACKAGE_IDENTIFIER = "com.sarankars.buddy-cli"


def package_macos_installer(
    project_root: Path,
    target: str,
    version: str,
    signing_identity: str,
) -> Path:
    """Build a signed PKG that installs Buddy into /usr/local/bin."""
    if not re.fullmatch(r"macos-(?:arm64|x64)", target):
        raise ValueError("target must be macos-arm64 or macos-x64")
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}", version):
        raise ValueError("version must contain three numeric components")
    if not signing_identity.strip():
        raise ValueError("a Developer ID Installer identity is required")

    binary = project_root / "dist" / "buddy"
    if not binary.is_file():
        raise FileNotFoundError(f"standalone binary does not exist: {binary}")

    release_dir = project_root / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    archive = release_dir / f"buddy-{target}.pkg"

    with tempfile.TemporaryDirectory(prefix="buddy-pkg-") as temporary_directory:
        package_root = Path(temporary_directory) / "root"
        install_directory = package_root / "usr" / "local" / "bin"
        install_directory.mkdir(parents=True)
        shutil.copy2(binary, install_directory / "buddy")
        subprocess.run(
            [
                "pkgbuild",
                "--root",
                str(package_root),
                "--install-location",
                "/",
                "--identifier",
                PACKAGE_IDENTIFIER,
                "--version",
                version,
                "--ownership",
                "recommended",
                "--sign",
                signing_identity,
                str(archive),
            ],
            check=True,
        )
    return archive


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--signing-identity", required=True)
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    archive = package_macos_installer(
        project_root,
        args.target,
        args.version,
        args.signing_identity,
    )
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
