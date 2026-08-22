"""Tests for standalone Buddy update discovery and installation."""

import hashlib
import io
import json
import stat
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from buddy_cli.paths import AppPaths
from buddy_cli.updater import (
    ReleaseAsset,
    UpdateError,
    UpdateInfo,
    Updater,
    _release_package,
)


class FakeResponse:
    def __init__(self, contents: bytes) -> None:
        self.contents = io.BytesIO(contents)

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.contents.close()

    def read(self, size: int = -1) -> bytes:
        return self.contents.read(size)


def asset_metadata(name: str, version: str, *, size: int = 100, digest=None):
    return {
        "name": name,
        "browser_download_url": (
            "https://github.com/sarankars/buddy_cli/releases/download/"
            f"v{version}/{name}"
        ),
        "size": size,
        "state": "uploaded",
        "digest": digest,
    }


def release_metadata(version: str, assets, *, prerelease: bool = False):
    return {
        "tag_name": f"v{version}",
        "html_url": f"https://github.com/sarankars/buddy_cli/releases/tag/v{version}",
        "draft": False,
        "prerelease": prerelease,
        "assets": assets,
    }


def update_info(
    package_name: str,
    archive_type: str,
    checksum: str,
    *,
    current_version: str = "0.3.4",
    latest_version: str = "0.3.5",
) -> UpdateInfo:
    package_url = (
        "https://github.com/sarankars/buddy_cli/releases/download/"
        f"v{latest_version}/{package_name}"
    )
    return UpdateInfo(
        current_version=current_version,
        latest_version=latest_version,
        release_url=(
            f"https://github.com/sarankars/buddy_cli/releases/tag/v{latest_version}"
        ),
        package=ReleaseAsset(
            package_name,
            package_url,
            100,
            f"sha256:{checksum}",
        ),
        checksum=ReleaseAsset(
            f"{package_name}.sha256",
            f"{package_url}.sha256",
            90,
        ),
        archive_type=archive_type,
    )


def checksum_contents(checksum: str, filename: str) -> bytes:
    return f"{checksum}  {filename}\n".encode("ascii")


def create_tar_archive(path: Path, contents: bytes, *, member_name: str = "buddy"):
    with tarfile.open(path, "w:gz") as bundle:
        member = tarfile.TarInfo(member_name)
        member.size = len(contents)
        member.mode = 0o755
        bundle.addfile(member, io.BytesIO(contents))


class UpdaterCheckTests(unittest.TestCase):
    def test_selects_release_packages_for_every_supported_target(self) -> None:
        cases = {
            ("darwin", "x86_64"): ("buddy-macos-x64.pkg", "pkg", "darwin"),
            ("darwin", "arm64"): ("buddy-macos-arm64.pkg", "pkg", "darwin"),
            ("linux", "amd64"): ("buddy-linux-x64.tar.gz", "tgz", "linux"),
            ("linux", "aarch64"): ("buddy-linux-arm64.tar.gz", "tgz", "linux"),
            ("win32", "x64"): ("buddy-windows-x64.zip", "zip", "windows"),
            ("win32", "arm64"): ("buddy-windows-arm64.zip", "zip", "windows"),
        }

        for platform_name, machine in cases:
            with self.subTest(platform=platform_name, machine=machine):
                self.assertEqual(
                    _release_package(platform_name, machine),
                    cases[(platform_name, machine)],
                )

    def test_selects_the_platform_package_from_latest_stable_release(self) -> None:
        version = "0.3.5"
        package_name = "buddy-macos-arm64.pkg"
        payload = release_metadata(
            version,
            [
                asset_metadata(package_name, version),
                asset_metadata(f"{package_name}.sha256", version),
            ],
        )
        requests = []

        def open_url(http_request, *, timeout):
            requests.append((http_request, timeout))
            return FakeResponse(json.dumps(payload).encode("utf-8"))

        with tempfile.TemporaryDirectory() as temporary_directory:
            updater = Updater(
                AppPaths(Path(temporary_directory)),
                current_version="0.3.4",
                platform_name="darwin",
                machine="arm64",
                open_url=open_url,
            )

            info = updater.check()

        self.assertTrue(info.update_available)
        self.assertFalse(info.current_is_newer)
        self.assertEqual(info.latest_version, version)
        self.assertEqual(info.package.name, package_name)
        self.assertEqual(info.archive_type, "pkg")
        self.assertEqual(requests[0][1], 15)
        self.assertEqual(
            requests[0][0].headers["Accept"],
            "application/vnd.github+json",
        )

    def test_detects_up_to_date_and_newer_development_versions(self) -> None:
        checksum = "a" * 64
        current = update_info(
            "buddy-linux-x64.tar.gz",
            "tgz",
            checksum,
            current_version="0.3.5",
            latest_version="0.3.5",
        )
        newer = update_info(
            "buddy-linux-x64.tar.gz",
            "tgz",
            checksum,
            current_version="0.4.0",
            latest_version="0.3.5",
        )

        self.assertFalse(current.update_available)
        self.assertFalse(current.current_is_newer)
        self.assertFalse(newer.update_available)
        self.assertTrue(newer.current_is_newer)

    def test_rejects_prerelease_missing_and_untrusted_assets(self) -> None:
        version = "0.3.5"
        package_name = "buddy-linux-x64.tar.gz"
        cases = [
            release_metadata(
                version,
                [asset_metadata(package_name, version)],
            ),
            release_metadata(
                version,
                [
                    {
                        **asset_metadata(package_name, version),
                        "browser_download_url": "https://example.com/buddy.tar.gz",
                    },
                    asset_metadata(f"{package_name}.sha256", version),
                ],
            ),
            release_metadata(
                version,
                [
                    asset_metadata(package_name, version),
                    asset_metadata(f"{package_name}.sha256", version),
                ],
                prerelease=True,
            ),
        ]

        for payload in cases:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as root:
                updater = Updater(
                    AppPaths(Path(root)),
                    platform_name="linux",
                    machine="x86_64",
                    open_url=lambda http_request, timeout, payload=payload: (
                        FakeResponse(json.dumps(payload).encode("utf-8"))
                    ),
                )
                with self.assertRaises(UpdateError):
                    updater.check()


class UpdaterInstallTests(unittest.TestCase):
    def _downloader_for(self, archive: Path, actual_checksum: str):
        def download(url, destination, expected_sha256, **kwargs):
            self.assertEqual(expected_sha256, actual_checksum)
            self.assertEqual(kwargs["resume_command"], "buddy update")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read_bytes())
            if kwargs.get("progress"):
                kwargs["progress"](
                    destination.stat().st_size, destination.stat().st_size
                )
            return destination

        return download

    def _open_checksum(self, contents: bytes):
        def open_url(http_request, *, timeout):
            return FakeResponse(contents)

        return open_url

    def test_atomically_replaces_linux_standalone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            current = root / "bin" / "buddy"
            current.parent.mkdir()
            current.write_bytes(b"old Buddy")
            current.chmod(0o755)
            archive = root / "release.tar.gz"
            create_tar_archive(archive, b"new Buddy")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            info = update_info("buddy-linux-x64.tar.gz", "tgz", digest)
            progress = []
            updater = Updater(
                AppPaths(root / "data"),
                current_version="0.3.4",
                platform_name="linux",
                machine="x86_64",
                executable=current,
                frozen=True,
                open_url=self._open_checksum(
                    checksum_contents(digest, info.package.name)
                ),
                downloader=self._downloader_for(archive, digest),
                run_process=lambda *args, **kwargs: subprocess.CompletedProcess(
                    args[0],
                    0,
                    stdout="buddy 0.3.5\n",
                    stderr="",
                ),
            )

            outcome = updater.install(
                info, progress=lambda done, total: progress.append((done, total))
            )

            self.assertEqual(current.read_bytes(), b"new Buddy")
            self.assertTrue(current.stat().st_mode & stat.S_IXUSR)
            self.assertTrue(outcome.restart_required)
            self.assertTrue(progress)

    def test_source_installation_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            python = root / "python"
            python.write_bytes(b"do not overwrite")
            info = update_info("buddy-linux-x64.tar.gz", "tgz", "a" * 64)
            updater = Updater(
                AppPaths(root / "data"),
                platform_name="linux",
                machine="x86_64",
                executable=python,
                frozen=False,
            )

            with self.assertRaisesRegex(UpdateError, "Python package manager"):
                updater.install(info)

            self.assertEqual(python.read_bytes(), b"do not overwrite")

    def test_rejects_an_archive_with_unexpected_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            current = root / "buddy"
            current.write_bytes(b"old")
            archive = root / "release.tar.gz"
            create_tar_archive(archive, b"malicious", member_name="../buddy")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            info = update_info("buddy-linux-x64.tar.gz", "tgz", digest)
            updater = Updater(
                AppPaths(root / "data"),
                platform_name="linux",
                machine="x86_64",
                executable=current,
                frozen=True,
                open_url=self._open_checksum(
                    checksum_contents(digest, info.package.name)
                ),
                downloader=self._downloader_for(archive, digest),
            )

            with self.assertRaisesRegex(UpdateError, "exactly one"):
                updater.install(info)

            self.assertEqual(current.read_bytes(), b"old")

    def test_stages_windows_replacement_after_the_current_process_exits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            current = root / "bin" / "buddy.exe"
            current.parent.mkdir()
            current.write_bytes(b"old Buddy")
            archive = root / "release.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("buddy.exe", b"new Buddy")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            info = update_info("buddy-windows-x64.zip", "zip", digest)
            spawned = []

            def spawn_process(command, **kwargs):
                spawned.append((command, kwargs))
                return object()

            updater = Updater(
                AppPaths(root / "data"),
                platform_name="win32",
                machine="amd64",
                executable=current,
                frozen=True,
                process_id=1234,
                open_url=self._open_checksum(
                    checksum_contents(digest, info.package.name)
                ),
                downloader=self._downloader_for(archive, digest),
                run_process=lambda *args, **kwargs: subprocess.CompletedProcess(
                    args[0],
                    0,
                    stdout="buddy 0.3.5\n",
                    stderr="",
                ),
                spawn_process=spawn_process,
                find_executable=lambda name: r"C:\Windows\powershell.exe",
            )

            outcome = updater.install(info)

            self.assertEqual(current.read_bytes(), b"old Buddy")
            self.assertTrue(outcome.restart_required)
            command, options = spawned[0]
            self.assertIn("1234", command)
            self.assertIn(str(current.resolve()), command)
            self.assertTrue(options["close_fds"])
            script = Path(command[command.index("-File") + 1])
            self.assertIn("Wait-Process", script.read_text(encoding="utf-8"))

    def test_verifies_and_opens_signed_macos_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            current = root / "buddy"
            current.write_bytes(b"old")
            installed = root / "usr" / "local" / "bin" / "buddy"
            installed.parent.mkdir(parents=True)
            installed.write_bytes(b"new")
            package = root / "release.pkg"
            package.write_bytes(b"signed package")
            digest = hashlib.sha256(package.read_bytes()).hexdigest()
            info = update_info("buddy-macos-arm64.pkg", "pkg", digest)
            commands = []

            def run_process(command, **kwargs):
                commands.append(command)
                stdout = "buddy 0.3.5\n" if command[0] == str(installed) else ""
                return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

            updater = Updater(
                AppPaths(root / "data"),
                platform_name="darwin",
                machine="arm64",
                executable=current,
                frozen=True,
                mac_install_path=installed,
                open_url=self._open_checksum(
                    checksum_contents(digest, info.package.name)
                ),
                downloader=self._downloader_for(package, digest),
                run_process=run_process,
            )

            outcome = updater.install(info)

            self.assertIn("updated to 0.3.5", outcome.message)
            self.assertEqual(
                commands[0][0:2], ["/usr/sbin/pkgutil", "--check-signature"]
            )
            self.assertEqual(
                commands[1][0:4], ["/usr/sbin/spctl", "--assess", "--type", "install"]
            )
            self.assertEqual(commands[2][0:2], ["/usr/bin/open", "-W"])
            self.assertEqual(commands[3], [str(installed), "--version"])

    def test_rejects_macos_installer_when_gatekeeper_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            package = root / "update.pkg"
            package.write_bytes(b"package")
            commands = []

            def run_process(command, **kwargs):
                commands.append(command)
                return_code = 1 if command[0] == "/usr/sbin/spctl" else 0
                return subprocess.CompletedProcess(
                    command,
                    return_code,
                    stdout="",
                    stderr="rejected" if return_code else "",
                )

            updater = Updater(
                AppPaths(root / "data"),
                run_process=run_process,
            )

            with self.assertRaisesRegex(UpdateError, "Gatekeeper rejected"):
                updater._install_macos(package, "0.3.5")

            self.assertEqual(len(commands), 2)

    def test_rejects_checksum_that_disagrees_with_github_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            current = root / "buddy"
            current.write_bytes(b"old")
            info = update_info("buddy-linux-x64.tar.gz", "tgz", "a" * 64)
            updater = Updater(
                AppPaths(root / "data"),
                platform_name="linux",
                machine="x86_64",
                executable=current,
                frozen=True,
                open_url=self._open_checksum(
                    checksum_contents("b" * 64, info.package.name)
                ),
            )

            with self.assertRaisesRegex(UpdateError, "GitHub's asset digest"):
                updater.install(info)


if __name__ == "__main__":
    unittest.main()
