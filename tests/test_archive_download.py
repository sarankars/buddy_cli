"""Tests for verified downloads and safe archive extraction."""

import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from buddy_cli.archive import ArchiveError, extract_archive
from buddy_cli.download import DownloadError, download_verified


class FakeDownloadResponse:
    def __init__(
        self,
        content: bytes,
        *,
        status: int = 200,
        content_range: str = "",
    ) -> None:
        self.content = io.BytesIO(content)
        self.headers = {"Content-Length": str(len(content))}
        if content_range:
            self.headers["Content-Range"] = content_range
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.content.close()

    def read(self, size: int = -1) -> bytes:
        return self.content.read(size)


class DownloadTests(unittest.TestCase):
    def test_download_is_published_after_checksum_verification(self) -> None:
        content = b"verified runtime"
        expected = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "runtime.zip"
            progress = []

            with patch(
                "buddy_cli.download.request.urlopen",
                return_value=FakeDownloadResponse(content),
            ):
                result = download_verified(
                    "https://example.invalid/runtime.zip",
                    destination,
                    expected,
                    progress=lambda completed, total: progress.append(
                        (completed, total)
                    ),
                )

            self.assertEqual(result.read_bytes(), content)
            self.assertEqual(progress[-1], (len(content), len(content)))

    def test_resumes_an_existing_partial_download(self) -> None:
        content = b"verified runtime"
        split_at = 9
        expected = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "runtime.zip"
            partial = destination.parent / ".runtime.zip.part"
            partial.write_bytes(content[:split_at])
            response = FakeDownloadResponse(
                content[split_at:],
                status=206,
                content_range=(f"bytes {split_at}-{len(content) - 1}/{len(content)}"),
            )

            with patch(
                "buddy_cli.download.request.urlopen",
                return_value=response,
            ) as open_url:
                result = download_verified(
                    "https://example.invalid/runtime.zip",
                    destination,
                    expected,
                )

            sent_request = open_url.call_args.args[0]
            self.assertEqual(sent_request.get_header("Range"), f"bytes={split_at}-")
            self.assertEqual(result.read_bytes(), content)

    def test_network_stall_preserves_partial_download_for_next_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "runtime.zip"
            partial = destination.parent / ".runtime.zip.part"
            partial.write_bytes(b"keep this progress")

            with (
                patch(
                    "buddy_cli.download.request.urlopen",
                    side_effect=TimeoutError("socket stalled"),
                ),
                self.assertRaisesRegex(DownloadError, "run 'buddy setup' again"),
            ):
                download_verified(
                    "https://example.invalid/runtime.zip",
                    destination,
                    "0" * 64,
                    max_attempts=1,
                )

            self.assertEqual(partial.read_bytes(), b"keep this progress")

    def test_retries_a_stalled_connection(self) -> None:
        content = b"verified runtime"
        expected = hashlib.sha256(content).hexdigest()
        statuses = []
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "runtime.zip"
            with (
                patch(
                    "buddy_cli.download.request.urlopen",
                    side_effect=[
                        TimeoutError("socket stalled"),
                        FakeDownloadResponse(content),
                    ],
                ) as open_url,
                patch("buddy_cli.download.time.sleep") as sleep,
            ):
                result = download_verified(
                    "https://example.invalid/runtime.zip",
                    destination,
                    expected,
                    status=statuses.append,
                )

            self.assertEqual(open_url.call_count, 2)
            sleep.assert_called_once_with(1)
            self.assertIn("Retrying", statuses[0])
            self.assertEqual(result.read_bytes(), content)

    def test_publishes_a_complete_partial_without_another_request(self) -> None:
        content = b"verified runtime"
        expected = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "runtime.zip"
            partial = destination.parent / ".runtime.zip.part"
            partial.write_bytes(content)

            with patch("buddy_cli.download.request.urlopen") as open_url:
                result = download_verified(
                    "https://example.invalid/runtime.zip",
                    destination,
                    expected,
                )

            open_url.assert_not_called()
            self.assertEqual(result.read_bytes(), content)

    def test_bad_checksum_removes_partial_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "runtime.zip"
            with (
                patch(
                    "buddy_cli.download.request.urlopen",
                    return_value=FakeDownloadResponse(b"corrupt"),
                ),
                self.assertRaises(DownloadError),
            ):
                download_verified(
                    "https://example.invalid/runtime.zip",
                    destination,
                    "0" * 64,
                )

            self.assertFalse(destination.exists())
            self.assertFalse((destination.parent / ".runtime.zip.part").exists())


class ArchiveTests(unittest.TestCase):
    def test_extracts_safe_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = root / "runtime.zip"
            destination = root / "destination"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("bin/ollama.exe", b"binary")

            extract_archive(archive, destination, "zip")

            self.assertEqual(
                (destination / "bin" / "ollama.exe").read_bytes(), b"binary"
            )

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            archive = root / "runtime.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("../outside", b"unsafe")

            with self.assertRaises(ArchiveError):
                extract_archive(archive, root / "destination", "zip")

            self.assertFalse((root / "outside").exists())
