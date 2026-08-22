"""Verify that a complete set of release archives and checksums is present."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Optional, Sequence

RELEASE_ARCHIVES = (
    "buddy-linux-arm64.tar.gz",
    "buddy-linux-x64.tar.gz",
    "buddy-macos-arm64.tar.gz",
    "buddy-macos-x64.tar.gz",
    "buddy-windows-arm64.zip",
    "buddy-windows-x64.zip",
)


class ReleaseAssetError(RuntimeError):
    """Raised when release assets are missing, unexpected, or corrupted."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_release_assets(directory: Path) -> Path:
    """Validate every platform archive and produce a combined checksum file."""
    expected = set(RELEASE_ARCHIVES)
    expected.update(f"{name}.sha256" for name in RELEASE_ARCHIVES)
    actual = {path.name for path in directory.iterdir() if path.is_file()}
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing:
        raise ReleaseAssetError(f"missing release assets: {', '.join(missing)}")
    if unexpected:
        raise ReleaseAssetError(f"unexpected release assets: {', '.join(unexpected)}")

    checksum_lines = []
    for archive_name in RELEASE_ARCHIVES:
        archive = directory / archive_name
        expected_line = f"{sha256_file(archive)}  {archive_name}"
        checksum_file = directory / f"{archive_name}.sha256"
        actual_line = checksum_file.read_text(encoding="utf-8").strip()
        if actual_line != expected_line:
            raise ReleaseAssetError(f"checksum verification failed: {archive_name}")
        checksum_lines.append(f"{expected_line}\n")

    combined = directory / "SHA256SUMS"
    combined.write_text("".join(checksum_lines), encoding="utf-8")
    return combined


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory", type=Path, help="Downloaded release asset directory"
    )
    args = parser.parse_args(argv)
    combined = verify_release_assets(args.directory)
    print(combined)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
