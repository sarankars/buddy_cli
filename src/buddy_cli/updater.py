"""Secure update discovery and installation for standalone Buddy releases."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib import error, parse, request

from buddy_cli import __version__
from buddy_cli.download import DownloadProgress, DownloadStatus, download_verified
from buddy_cli.paths import AppPaths
from buddy_cli.runtime_manifest import (
    normalize_architecture,
    normalize_operating_system,
)


class UpdateError(RuntimeError):
    """Raised when Buddy cannot safely check for or install an update."""


_REPOSITORY = "sarankars/buddy_cli"
_LATEST_RELEASE_API = f"https://api.github.com/repos/{_REPOSITORY}/releases/latest"
_GITHUB_API_VERSION = "2026-03-10"
_VERSION_PATTERN = re.compile(
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
)
_CHECKSUM_PATTERN = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9._-]+)\n?")
_MAX_API_RESPONSE = 2 * 1024 * 1024
_MAX_CHECKSUM_RESPONSE = 4096


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int
    digest: Optional[str] = None


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_url: str
    package: ReleaseAsset
    checksum: ReleaseAsset
    archive_type: str

    @property
    def update_available(self) -> bool:
        return _version_tuple(self.latest_version) > _version_tuple(
            self.current_version
        )

    @property
    def current_is_newer(self) -> bool:
        return _version_tuple(self.current_version) > _version_tuple(
            self.latest_version
        )


@dataclass(frozen=True)
class UpdateOutcome:
    message: str
    restart_required: bool = False


def _version_tuple(version: str) -> Tuple[int, int, int]:
    if not _VERSION_PATTERN.fullmatch(version):
        raise UpdateError(f"invalid Buddy version: {version!r}")
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def _release_package(
    platform_name: str,
    machine: str,
) -> Tuple[str, str, str]:
    operating_system = normalize_operating_system(platform_name)
    architecture = normalize_architecture(machine)
    release_architecture = {"amd64": "x64", "arm64": "arm64"}.get(architecture)
    if release_architecture is None:
        raise UpdateError(
            f"Buddy updates are not available for architecture {architecture}"
        )

    if operating_system == "darwin":
        return (
            f"buddy-macos-{release_architecture}.pkg",
            "pkg",
            operating_system,
        )
    if operating_system == "windows":
        return (
            f"buddy-windows-{release_architecture}.zip",
            "zip",
            operating_system,
        )
    if operating_system == "linux":
        return (
            f"buddy-linux-{release_architecture}.tar.gz",
            "tgz",
            operating_system,
        )
    raise UpdateError(f"Buddy updates are not available for {operating_system}")


def _asset_from_json(value: object, *, tag: str) -> ReleaseAsset:
    if not isinstance(value, dict):
        raise UpdateError("GitHub returned invalid release asset metadata")
    name = value.get("name")
    download_url = value.get("browser_download_url")
    size = value.get("size")
    state = value.get("state")
    digest = value.get("digest")
    if (
        not isinstance(name, str)
        or not isinstance(download_url, str)
        or not isinstance(size, int)
        or size < 1
        or state != "uploaded"
    ):
        raise UpdateError("GitHub returned incomplete release asset metadata")

    expected_path = f"/{_REPOSITORY}/releases/download/{tag}/{name}"
    parsed_url = parse.urlparse(download_url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != "github.com"
        or parsed_url.path != expected_path
        or parsed_url.params
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise UpdateError(f"release asset has an untrusted download URL: {name}")
    if digest is not None and not isinstance(digest, str):
        raise UpdateError(f"release asset has an invalid digest: {name}")
    return ReleaseAsset(name, download_url, size, digest)


def _extract_binary(
    archive: Path,
    destination: Path,
    archive_type: str,
) -> None:
    expected_name = "buddy.exe" if archive_type == "zip" else "buddy"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if archive_type == "zip":
        try:
            with zipfile.ZipFile(archive) as bundle:
                members = bundle.infolist()
                if len(members) != 1 or members[0].filename != expected_name:
                    raise UpdateError(
                        "update archive does not contain exactly one Buddy executable"
                    )
                mode = members[0].external_attr >> 16
                if members[0].is_dir() or stat.S_ISLNK(mode):
                    raise UpdateError("update archive contains an invalid executable")
                with (
                    bundle.open(members[0]) as source,
                    destination.open("wb") as target,
                ):
                    shutil.copyfileobj(source, target)
        except zipfile.BadZipFile as exc:
            raise UpdateError("downloaded update is not a valid ZIP archive") from exc
    elif archive_type == "tgz":
        try:
            with tarfile.open(archive, mode="r:gz") as bundle:
                members = bundle.getmembers()
                if (
                    len(members) != 1
                    or members[0].name != expected_name
                    or not members[0].isreg()
                ):
                    raise UpdateError(
                        "update archive does not contain exactly one Buddy executable"
                    )
                source = bundle.extractfile(members[0])
                if source is None:
                    raise UpdateError("update archive executable could not be read")
                with source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
        except tarfile.TarError as exc:
            raise UpdateError("downloaded update is not a valid tar archive") from exc
    else:
        raise UpdateError(f"unsupported executable archive type: {archive_type}")

    if destination.stat().st_size < 1:
        raise UpdateError("update archive contains an empty executable")
    destination.chmod(0o755)


class Updater:
    """Check GitHub Releases and safely update a standalone Buddy executable."""

    def __init__(
        self,
        paths: AppPaths,
        *,
        current_version: str = __version__,
        platform_name: Optional[str] = None,
        machine: Optional[str] = None,
        executable: Optional[Path] = None,
        frozen: Optional[bool] = None,
        open_url: Callable[..., Any] = request.urlopen,
        downloader: Callable[..., Path] = download_verified,
        run_process: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        spawn_process: Callable[..., subprocess.Popen] = subprocess.Popen,
        find_executable: Callable[[str], Optional[str]] = shutil.which,
        process_id: Optional[int] = None,
        mac_install_path: Path = Path("/usr/local/bin/buddy"),
    ) -> None:
        self.paths = paths
        self.current_version = current_version
        self.platform_name = platform_name or sys.platform
        self.machine = machine or platform.machine()
        self.executable = Path(executable or sys.executable)
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self.open_url = open_url
        self.downloader = downloader
        self.run_process = run_process
        self.spawn_process = spawn_process
        self.find_executable = find_executable
        self.process_id = os.getpid() if process_id is None else process_id
        self.mac_install_path = mac_install_path

    @staticmethod
    def _request(url: str, *, accept: str) -> request.Request:
        return request.Request(
            url,
            headers={
                "Accept": accept,
                "User-Agent": f"Buddy-CLI/{__version__}",
                "X-GitHub-Api-Version": _GITHUB_API_VERSION,
            },
        )

    def _read_url(self, url: str, *, accept: str, limit: int) -> bytes:
        try:
            with self.open_url(
                self._request(url, accept=accept),
                timeout=15,
            ) as response:
                raw = response.read(limit + 1)
        except (error.URLError, error.HTTPError, TimeoutError, OSError) as exc:
            raise UpdateError(f"could not retrieve update information: {exc}") from exc
        if len(raw) > limit:
            raise UpdateError("update information exceeded the safe size limit")
        return raw

    def check(self) -> UpdateInfo:
        """Return latest stable release information for this platform."""
        raw = self._read_url(
            _LATEST_RELEASE_API,
            accept="application/vnd.github+json",
            limit=_MAX_API_RESPONSE,
        )
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UpdateError("GitHub returned invalid release information") from exc
        if not isinstance(value, dict):
            raise UpdateError("GitHub returned unexpected release information")

        tag = value.get("tag_name")
        release_url = value.get("html_url")
        if (
            not isinstance(tag, str)
            or not tag.startswith("v")
            or not _VERSION_PATTERN.fullmatch(tag[1:])
            or not isinstance(release_url, str)
            or value.get("draft") is not False
            or value.get("prerelease") is not False
        ):
            raise UpdateError(
                "GitHub's latest release metadata is not a stable release"
            )
        expected_release_url = f"https://github.com/{_REPOSITORY}/releases/tag/{tag}"
        if release_url != expected_release_url:
            raise UpdateError("GitHub returned an untrusted release URL")

        package_name, archive_type, _ = _release_package(
            self.platform_name,
            self.machine,
        )
        checksum_name = f"{package_name}.sha256"
        raw_assets = value.get("assets")
        if not isinstance(raw_assets, list):
            raise UpdateError("GitHub release does not contain an asset list")
        assets: Dict[str, ReleaseAsset] = {}
        for raw_asset in raw_assets:
            asset = _asset_from_json(raw_asset, tag=tag)
            if asset.name in assets:
                raise UpdateError(
                    f"GitHub release contains duplicate asset {asset.name}"
                )
            assets[asset.name] = asset
        if package_name not in assets or checksum_name not in assets:
            raise UpdateError(
                f"GitHub release is missing {package_name} or its checksum"
            )

        return UpdateInfo(
            current_version=self.current_version,
            latest_version=tag[1:],
            release_url=release_url,
            package=assets[package_name],
            checksum=assets[checksum_name],
            archive_type=archive_type,
        )

    def _expected_checksum(self, info: UpdateInfo) -> str:
        raw = self._read_url(
            info.checksum.download_url,
            accept="application/octet-stream",
            limit=_MAX_CHECKSUM_RESPONSE,
        )
        try:
            contents = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise UpdateError("release checksum is not ASCII text") from exc
        match = _CHECKSUM_PATTERN.fullmatch(contents)
        if match is None or match.group(2) != info.package.name:
            raise UpdateError("release checksum file has invalid contents")
        expected = match.group(1)
        if (
            info.package.digest is not None
            and info.package.digest != f"sha256:{expected}"
        ):
            raise UpdateError("release checksum does not match GitHub's asset digest")
        return expected

    def _smoke_test(self, binary: Path, version: str) -> None:
        try:
            completed = self.run_process(
                [str(binary), "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise UpdateError(
                f"downloaded Buddy executable could not run: {exc}"
            ) from exc
        expected = f"buddy {version}"
        if completed.returncode != 0 or completed.stdout.strip() != expected:
            raise UpdateError(
                "downloaded Buddy executable failed its version smoke test"
            )

    def _current_executable(self) -> Path:
        if not self.frozen:
            raise UpdateError(
                "automatic installation is available only for the standalone Buddy "
                "executable; update this source installation with its Python package "
                "manager"
            )
        try:
            current = self.executable.resolve(strict=True)
        except OSError as exc:
            raise UpdateError(
                f"could not locate the running Buddy executable: {exc}"
            ) from exc
        if not current.is_file():
            raise UpdateError("the running Buddy executable is not a regular file")
        return current

    def _install_linux(
        self, staged: Path, current: Path, version: str
    ) -> UpdateOutcome:
        self._smoke_test(staged, version)
        temporary_path: Optional[Path] = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=".buddy-update-",
                dir=str(current.parent),
            )
            temporary_path = Path(raw_path)
            with (
                os.fdopen(descriptor, "wb") as destination,
                staged.open("rb") as source,
            ):
                shutil.copyfileobj(source, destination)
                destination.flush()
                os.fsync(destination.fileno())
            temporary_path.chmod(stat.S_IMODE(current.stat().st_mode))
            os.replace(str(temporary_path), str(current))
        except OSError as exc:
            raise UpdateError(
                f"could not replace {current}: {exc}; reinstall Buddy in a writable "
                "location or run the update with sufficient permissions"
            ) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return UpdateOutcome(
            f"Buddy was updated to {version}. Restart Buddy to use the new version.",
            restart_required=True,
        )

    def _install_windows(
        self, staged: Path, current: Path, version: str
    ) -> UpdateOutcome:
        self._smoke_test(staged, version)
        powershell = self.find_executable("powershell.exe")
        if powershell is None:
            raise UpdateError("PowerShell is required to finish a Windows update")
        try:
            descriptor, probe = tempfile.mkstemp(
                prefix=".buddy-write-test-",
                dir=str(current.parent),
            )
            os.close(descriptor)
            Path(probe).unlink()
        except OSError as exc:
            raise UpdateError(
                f"Buddy cannot update {current} without write permission"
            ) from exc

        script = staged.with_name("finish-buddy-update.ps1")
        script.write_text(
            "param([int]$BuddyPid, [string]$Source, [string]$Target)\n"
            "$ErrorActionPreference = 'Stop'\n"
            "Wait-Process -Id $BuddyPid -ErrorAction SilentlyContinue\n"
            "Move-Item -LiteralPath $Source -Destination $Target -Force\n"
            "Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force "
            "-ErrorAction SilentlyContinue\n",
            encoding="utf-8",
        )
        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess,
            "DETACHED_PROCESS",
            0,
        )
        try:
            self.spawn_process(
                [
                    powershell,
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-BuddyPid",
                    str(self.process_id),
                    "-Source",
                    str(staged),
                    "-Target",
                    str(current),
                ],
                close_fds=True,
                creationflags=creation_flags,
            )
        except OSError as exc:
            script.unlink(missing_ok=True)
            raise UpdateError(f"could not schedule the Windows update: {exc}") from exc
        return UpdateOutcome(
            f"Buddy {version} is staged and will finish installing after this "
            "command exits. Start Buddy again in a few seconds.",
            restart_required=True,
        )

    def _install_macos(self, package: Path, version: str) -> UpdateOutcome:
        try:
            signature = self.run_process(
                ["/usr/sbin/pkgutil", "--check-signature", str(package)],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise UpdateError(f"could not verify the macOS installer: {exc}") from exc
        if signature.returncode != 0:
            raise UpdateError("the macOS installer signature is invalid")
        try:
            assessment = self.run_process(
                [
                    "/usr/sbin/spctl",
                    "--assess",
                    "--type",
                    "install",
                    "--verbose=2",
                    str(package),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise UpdateError(f"could not assess the macOS installer: {exc}") from exc
        if assessment.returncode != 0:
            raise UpdateError("macOS Gatekeeper rejected the update installer")
        try:
            opened = self.run_process(
                ["/usr/bin/open", "-W", str(package)],
                check=False,
                timeout=None,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise UpdateError(f"could not open the macOS installer: {exc}") from exc
        if opened.returncode != 0:
            raise UpdateError("the macOS installer exited unsuccessfully")
        self._smoke_test(self.mac_install_path, version)
        return UpdateOutcome(
            f"Buddy was updated to {version} at {self.mac_install_path}.",
            restart_required=True,
        )

    def install(
        self,
        info: UpdateInfo,
        *,
        progress: Optional[DownloadProgress] = None,
        status: Optional[DownloadStatus] = None,
    ) -> UpdateOutcome:
        """Download, verify, and install the selected standalone release."""
        if not info.update_available:
            raise UpdateError(
                "the selected release is not newer than this Buddy version"
            )
        current = self._current_executable()
        expected_checksum = self._expected_checksum(info)
        update_dir = self.paths.updates_dir / f"v{info.latest_version}"
        try:
            update_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise UpdateError(f"could not create update storage: {exc}") from exc
        package = update_dir / info.package.name
        try:
            self.downloader(
                info.package.download_url,
                package,
                expected_checksum,
                progress=progress,
                status=status,
                resume_command="buddy update",
            )
        except Exception as exc:
            if isinstance(exc, UpdateError):
                raise
            raise UpdateError(f"could not download the Buddy update: {exc}") from exc

        _, _, operating_system = _release_package(
            self.platform_name,
            self.machine,
        )
        try:
            if operating_system == "darwin":
                return self._install_macos(package, info.latest_version)

            staged_name = "buddy.exe" if operating_system == "windows" else "buddy"
            staged = update_dir / f"new-{staged_name}"
            _extract_binary(package, staged, info.archive_type)
            if operating_system == "windows":
                return self._install_windows(staged, current, info.latest_version)
            return self._install_linux(staged, current, info.latest_version)
        except UpdateError:
            raise
        except OSError as exc:
            raise UpdateError(f"could not prepare the Buddy update: {exc}") from exc
