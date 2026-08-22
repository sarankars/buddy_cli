"""Tests for final release asset verification."""

import tempfile
import unittest
from pathlib import Path

from scripts.checksum import write_checksum
from scripts.verify_release_assets import (
    RELEASE_ARCHIVES,
    ReleaseAssetError,
    verify_release_assets,
)


def create_release_assets(root: Path) -> None:
    for name in RELEASE_ARCHIVES:
        archive = root / name
        archive.write_bytes(f"contents of {name}".encode())
        write_checksum(archive)


class VerifyReleaseAssetsTests(unittest.TestCase):
    def test_verifies_all_assets_and_creates_combined_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            create_release_assets(root)

            combined = verify_release_assets(root)

            lines = combined.read_text().splitlines()
            self.assertEqual(len(lines), len(RELEASE_ARCHIVES))
            self.assertTrue(lines[0].endswith(f"  {RELEASE_ARCHIVES[0]}"))

    def test_rejects_a_missing_platform(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            create_release_assets(root)
            (root / RELEASE_ARCHIVES[0]).unlink()

            with self.assertRaisesRegex(ReleaseAssetError, "missing release assets"):
                verify_release_assets(root)

    def test_rejects_a_corrupted_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            create_release_assets(root)
            (root / RELEASE_ARCHIVES[0]).write_bytes(b"tampered")

            with self.assertRaisesRegex(ReleaseAssetError, "checksum verification"):
                verify_release_assets(root)

    def test_rejects_non_portable_checksum_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            create_release_assets(root)
            checksum = root / f"{RELEASE_ARCHIVES[0]}.sha256"
            checksum.write_bytes(checksum.read_bytes().replace(b"\n", b"\r\n"))

            with self.assertRaisesRegex(ReleaseAssetError, "checksum verification"):
                verify_release_assets(root)


if __name__ == "__main__":
    unittest.main()
