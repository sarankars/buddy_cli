"""Tests for release packaging."""

import stat
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.package_standalone import package_binary, write_checksum


class PackageStandaloneTests(unittest.TestCase):
    def test_packages_posix_binary_with_executable_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            binary = root / "dist" / "buddy"
            binary.parent.mkdir()
            binary.write_bytes(b"standalone")
            binary.chmod(0o755)

            archive = package_binary(root, "linux-x64", windows=False)

            with tarfile.open(archive, mode="r:gz") as bundle:
                member = bundle.getmember("buddy")
                self.assertTrue(member.mode & stat.S_IXUSR)
                extracted = bundle.extractfile(member)
                self.assertIsNotNone(extracted)
                self.assertEqual(extracted.read(), b"standalone")
            self.assertRegex(
                archive.with_name(f"{archive.name}.sha256").read_text(),
                rf"^[0-9a-f]{{64}}  {archive.name}\n$",
            )

    def test_packages_windows_binary_as_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            binary = root / "dist" / "buddy.exe"
            binary.parent.mkdir()
            binary.write_bytes(b"standalone")

            archive = package_binary(root, "windows-arm64", windows=True)

            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(bundle.namelist(), ["buddy.exe"])
                self.assertEqual(bundle.read("buddy.exe"), b"standalone")
            self.assertTrue(archive.with_name(f"{archive.name}.sha256").is_file())

    def test_checksum_changes_when_archive_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = Path(temporary_directory) / "buddy.zip"
            archive.write_bytes(b"first")
            checksum = write_checksum(archive)
            first = checksum.read_text()

            archive.write_bytes(b"second")
            write_checksum(archive)

            self.assertNotEqual(first, checksum.read_text())

    def test_rejects_unsafe_target_name(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            self.assertRaises(ValueError),
        ):
            package_binary(
                Path(temporary_directory),
                "../outside",
                windows=False,
            )


if __name__ == "__main__":
    unittest.main()
