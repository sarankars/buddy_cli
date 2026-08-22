"""Smoke-test and package a platform-native Buddy executable."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Optional, Sequence


def write_checksum(archive: Path) -> Path:
    """Write a sha256sum-compatible checksum beside an archive."""
    digest = hashlib.sha256()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum = archive.with_name(f"{archive.name}.sha256")
    checksum.write_bytes(f"{digest.hexdigest()}  {archive.name}\n".encode("ascii"))
    return checksum


def package_binary(
    project_root: Path,
    target: str,
    *,
    windows: Optional[bool] = None,
) -> Path:
    """Package the built binary and return the release archive path."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", target):
        raise ValueError("target may contain only letters, numbers, '.', '_', and '-'")

    is_windows = os.name == "nt" if windows is None else windows
    binary_name = "buddy.exe" if is_windows else "buddy"
    binary = project_root / "dist" / binary_name
    if not binary.is_file():
        raise FileNotFoundError(f"standalone binary does not exist: {binary}")

    release_dir = project_root / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    if is_windows:
        archive = release_dir / f"buddy-{target}.zip"
        with zipfile.ZipFile(
            archive,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as bundle:
            bundle.write(binary, arcname=binary_name)
    else:
        archive = release_dir / f"buddy-{target}.tar.gz"
        with tarfile.open(archive, mode="w:gz") as bundle:
            bundle.add(binary, arcname=binary_name, recursive=False)
    write_checksum(archive)
    return archive


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Release target name")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run the standalone executable before packaging it.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    binary_name = "buddy.exe" if os.name == "nt" else "buddy"
    binary = project_root / "dist" / binary_name
    if args.smoke_test:
        subprocess.run([str(binary), "--version"], check=True)
    archive = package_binary(project_root, args.target)
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
