"""Verified HTTP downloads."""

from __future__ import annotations

import hashlib
import http.client
import os
import socket
import time
from pathlib import Path
from typing import Any, Callable, Optional
from urllib import error, request

from buddy_cli import __version__


class DownloadError(RuntimeError):
    """Raised when a runtime download fails verification."""


DownloadProgress = Callable[[int, Optional[int]], None]
DownloadStatus = Callable[[str], None]

_CHUNK_SIZE = 64 * 1024


def _digest_partial(path: Path) -> tuple[Any, int]:
    digest = hashlib.sha256()
    downloaded = 0
    if path.exists():
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                downloaded += len(chunk)
    return digest, downloaded


def _response_status(response: Any) -> int:
    status = getattr(response, "status", None)
    if status is not None:
        return int(status)
    getcode = getattr(response, "getcode", None)
    return int(getcode()) if getcode else 200


def _response_total(response: Any, resumed_at: int) -> Optional[int]:
    headers = response.headers
    content_range = headers.get("Content-Range")
    if content_range and "/" in content_range:
        total = content_range.rsplit("/", 1)[1]
        if total != "*":
            return int(total)

    content_length = headers.get("Content-Length")
    if not content_length:
        return None
    return resumed_at + int(content_length)


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, error.HTTPError):
        return exc.code in {408, 425, 429} or 500 <= exc.code < 600
    return isinstance(
        exc,
        (
            error.URLError,
            TimeoutError,
            socket.timeout,
            ConnectionError,
            http.client.IncompleteRead,
            http.client.RemoteDisconnected,
        ),
    )


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
    status: Optional[DownloadStatus] = None,
    timeout: int = 15,
    max_attempts: int = 4,
    low_speed_limit: int = 16 * 1024,
    low_speed_window: int = 30,
    resume_command: str = "buddy setup",
) -> Path:
    """Download, resume, and publish a file after SHA-256 verification."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.part")

    for attempt in range(1, max_attempts + 1):
        digest, resumed_at = _digest_partial(partial)
        if resumed_at and digest.hexdigest().lower() == expected_sha256.lower():
            if progress:
                progress(resumed_at, resumed_at)
            os.replace(str(partial), str(destination))
            return destination

        headers = {
            "Accept-Encoding": "identity",
            "User-Agent": f"Buddy-CLI/{__version__}",
        }
        if resumed_at:
            headers["Range"] = f"bytes={resumed_at}-"
            if status:
                status(f"Resuming download from {resumed_at:,} bytes")

        http_request = request.Request(url, headers=headers)
        try:
            with request.urlopen(http_request, timeout=timeout) as response:
                response_status = _response_status(response)
                if resumed_at and response_status != 206:
                    # Some proxies ignore Range. Restart safely using the full response.
                    digest = hashlib.sha256()
                    resumed_at = 0

                total = _response_total(response, resumed_at)
                mode = "ab" if resumed_at else "wb"
                downloaded = resumed_at
                attempt_started_at = time.monotonic()
                if progress:
                    progress(downloaded, total)

                with partial.open(mode) as handle:
                    while True:
                        chunk = response.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        handle.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        if progress:
                            progress(downloaded, total)
                        attempt_elapsed = time.monotonic() - attempt_started_at
                        transferred_this_attempt = downloaded - resumed_at
                        if (
                            attempt < max_attempts
                            and attempt_elapsed >= low_speed_window
                            and transferred_this_attempt / attempt_elapsed
                            < low_speed_limit
                        ):
                            raise TimeoutError(
                                "transfer speed stayed below "
                                f"{low_speed_limit // 1024} KB/s for "
                                f"{low_speed_window}s"
                            )
                    handle.flush()
                    os.fsync(handle.fileno())

            actual_sha256 = digest.hexdigest()
            if actual_sha256.lower() != expected_sha256.lower():
                partial.unlink(missing_ok=True)
                raise DownloadError(
                    "download checksum mismatch: "
                    f"expected {expected_sha256}, received {actual_sha256}"
                )
            os.replace(str(partial), str(destination))
            return destination
        except Exception as exc:
            if not _retryable(exc) or attempt == max_attempts:
                if _retryable(exc):
                    raise DownloadError(
                        f"download stalled after {max_attempts} attempts; "
                        f"run '{resume_command}' again to resume"
                    ) from exc
                raise

            retry_delay = min(2 ** (attempt - 1), 4)
            if status:
                status(
                    f"Download paused ({exc}). Retrying in {retry_delay}s "
                    f"(attempt {attempt + 1}/{max_attempts})"
                )
            time.sleep(retry_delay)

    raise DownloadError("download did not complete")
