"""Verified HTTP downloads."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Callable, Optional
from urllib import request


class DownloadError(RuntimeError):
    """Raised when a runtime download fails verification."""


DownloadProgress = Callable[[int, Optional[int]], None]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(
    url: str,
    destination: Path,
    expected_sha256: str,
    *,
    progress: Optional[DownloadProgress] = None,
    timeout: int = 60,
) -> Path:
    """Download a URL and atomically publish it after SHA-256 verification."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.part")
    partial.unlink(missing_ok=True)
    digest = hashlib.sha256()
    downloaded = 0

    http_request = request.Request(
        url,
        headers={"User-Agent": "Buddy-CLI/0.1"},
    )

    try:
        with request.urlopen(http_request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
            total = int(content_length) if content_length else None
            with partial.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(downloaded, total)
                handle.flush()
                os.fsync(handle.fileno())

        actual_sha256 = digest.hexdigest()
        if actual_sha256.lower() != expected_sha256.lower():
            raise DownloadError(
                "download checksum mismatch: "
                f"expected {expected_sha256}, received {actual_sha256}"
            )
        os.replace(str(partial), str(destination))
        return destination
    except Exception:
        partial.unlink(missing_ok=True)
        raise
