"""Tests for signed macOS installer packaging."""

import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.package_macos_installer import package_macos_installer


class PackageMacosInstallerTests(unittest.TestCase):
    def test_builds_signed_installer_with_executable_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            binary = root / "dist" / "buddy"
            binary.parent.mkdir()
            binary.write_bytes(b"standalone")
            binary.chmod(0o755)

            def fake_pkgbuild(command: list[str], *, check: bool) -> None:
                self.assertTrue(check)
                package_root = Path(command[command.index("--root") + 1])
                installed = package_root / "usr" / "local" / "bin" / "buddy"
                self.assertEqual(installed.read_bytes(), b"standalone")
                self.assertTrue(installed.stat().st_mode & stat.S_IXUSR)
                self.assertIn("Developer ID Installer: Buddy (TEAMID)", command)
                Path(command[-1]).write_bytes(b"signed package")

            with patch(
                "scripts.package_macos_installer.subprocess.run",
                side_effect=fake_pkgbuild,
            ):
                archive = package_macos_installer(
                    root,
                    "macos-arm64",
                    "0.3.2",
                    "Developer ID Installer: Buddy (TEAMID)",
                )

            self.assertEqual(archive.name, "buddy-macos-arm64.pkg")
            self.assertEqual(archive.read_bytes(), b"signed package")

    def test_rejects_invalid_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for target, version, identity in (
                ("linux-arm64", "0.3.2", "Developer ID Installer"),
                ("macos-arm64", "0.3.2-beta.1", "Developer ID Installer"),
                ("macos-arm64", "0.3.2", ""),
            ):
                with (
                    self.subTest(target=target, version=version, identity=identity),
                    self.assertRaises(ValueError),
                ):
                    package_macos_installer(root, target, version, identity)


if __name__ == "__main__":
    unittest.main()
