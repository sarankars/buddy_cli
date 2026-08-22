"""Verify that a complete set of release archives and checksums is present."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

if __package__:
    from .checksum import sha256_file
else:
    from checksum import sha256_file

RELEASE_ARCHIVES = (
    "buddy-linux-arm64.tar.gz",
    "buddy-linux-x64.tar.gz",
    "buddy-macos-arm64.pkg",
    "buddy-macos-x64.pkg",
    "buddy-windows-arm64.zip",
    "buddy-windows-x64.zip",
)


class ReleaseAssetError(RuntimeError):
    """Raised when release assets are missing, unexpected, or corrupted."""


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
        if checksum_file.read_bytes() != f"{expected_line}\n".encode("ascii"):
            raise ReleaseAssetError(f"checksum verification failed: {archive_name}")
        checksum_lines.append(f"{expected_line}\n")

    combined = directory / "SHA256SUMS"
    combined.write_bytes("".join(checksum_lines).encode("ascii"))
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
