"""Generate portable SHA-256 checksum files for release assets."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Optional, Sequence


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksum(archive: Path) -> Path:
    """Write a sha256sum-compatible LF-only checksum beside an archive."""
    checksum = archive.with_name(f"{archive.name}.sha256")
    checksum.write_bytes(f"{sha256_file(archive)}  {archive.name}\n".encode("ascii"))
    return checksum


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args(argv)
    for archive in args.archives:
        print(write_checksum(archive))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
