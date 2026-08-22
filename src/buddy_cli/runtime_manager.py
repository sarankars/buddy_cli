"""Discover, install, and start Ollama runtimes."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib import parse

from buddy_cli.archive import extract_archive
from buddy_cli.config import BuddyConfig
from buddy_cli.constants import (
    DEFAULT_OLLAMA_BASE_URL,
    MANAGED_OLLAMA_BASE_URL,
    OLLAMA_RUNTIME_VERSION,
)
from buddy_cli.download import DownloadProgress, download_verified, sha256_file
from buddy_cli.ollama import OllamaClient, OllamaError
from buddy_cli.paths import AppPaths
from buddy_cli.runtime_manifest import RuntimeSpec, resolve_runtime_spec


class RuntimeManagerError(RuntimeError):
    """Raised when an Ollama runtime cannot be prepared."""


@dataclass(frozen=True)
class RuntimeSelection:
    provider: str
    base_url: str
    executable: Optional[Path]
    runtime_version: Optional[str]


RuntimeStatus = Callable[[str], None]


class RuntimeManager:
    """Manage system and Buddy-owned Ollama processes."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    @staticmethod
    def api_is_ready(base_url: str) -> bool:
        try:
            OllamaClient(base_url, timeout=1.0).get_version()
            return True
        except (OllamaError, ValueError):
            return False

    @staticmethod
    def find_system_executable() -> Optional[Path]:
        executable = shutil.which("ollama")
        if executable:
            return Path(executable)

        candidates = []
        if sys.platform == "darwin":
            candidates.extend(
                [
                    Path("/Applications/Ollama.app/Contents/Resources/ollama"),
                    Path.home()
                    / "Applications"
                    / "Ollama.app"
                    / "Contents"
                    / "Resources"
                    / "ollama",
                ]
            )
        elif sys.platform == "win32":
            local_app_data = os.environ.get("LOCALAPPDATA")
            if local_app_data:
                candidates.append(
                    Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"
                )

        return next((path for path in candidates if path.is_file()), None)

    def installation_dir(self, spec: RuntimeSpec) -> Path:
        return self.paths.runtimes_dir / spec.installation_name

    @staticmethod
    def _find_executable(root: Path) -> Optional[Path]:
        candidates = ("ollama.exe",) if os.name == "nt" else ("ollama",)
        for name in candidates:
            matches = [path for path in root.rglob(name) if path.is_file()]
            if matches:
                matches.sort(key=lambda path: (len(path.parts), str(path)))
                return matches[0]
        return None

    def find_managed_executable(self) -> Optional[Path]:
        try:
            spec = resolve_runtime_spec()
        except Exception:
            return None
        installation = self.installation_dir(spec)
        return self._find_executable(installation) if installation.exists() else None

    def install_managed(
        self,
        *,
        download_progress: Optional[DownloadProgress] = None,
        status_callback: Optional[RuntimeStatus] = None,
    ) -> RuntimeSelection:
        spec = resolve_runtime_spec()
        self.paths.ensure_directories()
        installation = self.installation_dir(spec)
        existing = (
            self._find_executable(installation) if installation.exists() else None
        )
        if existing:
            return RuntimeSelection(
                provider="managed",
                base_url=MANAGED_OLLAMA_BASE_URL,
                executable=existing,
                runtime_version=spec.version,
            )

        archive = self.paths.downloads_dir / spec.asset_name
        if archive.exists() and sha256_file(archive) != spec.sha256:
            archive.unlink()
        if not archive.exists():
            if status_callback:
                status_callback(f"Downloading Ollama {spec.version}")
            download_verified(
                spec.url,
                archive,
                spec.sha256,
                progress=download_progress,
            )

        staged: Optional[Path] = Path(
            tempfile.mkdtemp(prefix=".ollama-stage-", dir=str(self.paths.runtimes_dir))
        )
        try:
            if status_callback:
                status_callback("Extracting the verified Ollama runtime")
            extract_archive(archive, staged, spec.archive_type)
            staged_executable = self._find_executable(staged)
            if staged_executable is None:
                raise RuntimeManagerError(
                    "the Ollama archive did not contain an executable"
                )

            if os.name != "nt":
                staged_executable.chmod(
                    staged_executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
                )
            relative_executable = staged_executable.relative_to(staged)

            if installation.exists():
                shutil.rmtree(installation)
            os.replace(str(staged), str(installation))
            staged = None
            archive.unlink(missing_ok=True)
            executable = installation / relative_executable
            return RuntimeSelection(
                provider="managed",
                base_url=MANAGED_OLLAMA_BASE_URL,
                executable=executable,
                runtime_version=spec.version,
            )
        finally:
            if staged is not None and staged.exists():
                shutil.rmtree(staged)

    def start(self, selection: RuntimeSelection) -> None:
        if self.api_is_ready(selection.base_url):
            return
        if selection.executable is None or not selection.executable.exists():
            raise RuntimeManagerError("the configured Ollama executable does not exist")

        self.paths.ensure_directories()
        environment = os.environ.copy()
        if selection.provider == "managed":
            parsed = parse.urlparse(selection.base_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 11435
            environment["OLLAMA_HOST"] = f"{host}:{port}"
            environment["OLLAMA_MODELS"] = str(self.paths.models_dir)

        creation_flags = 0
        popen_options = {"start_new_session": True}
        if os.name == "nt":
            creation_flags = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            ) | getattr(subprocess, "DETACHED_PROCESS", 0)
            popen_options = {}

        with self.paths.ollama_log_file.open("ab") as log_handle:
            try:
                process = subprocess.Popen(
                    [str(selection.executable), "serve"],
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    creationflags=creation_flags,
                    **popen_options,
                )
            except OSError as exc:
                raise RuntimeManagerError(f"could not start Ollama: {exc}") from exc

        self.paths.ollama_pid_file.write_text(f"{process.pid}\n", encoding="utf-8")
        try:
            OllamaClient(selection.base_url, timeout=1.0).wait_until_ready(timeout=45)
        except OllamaError:
            process.terminate()
            raise

    def selection_from_config(self, config: BuddyConfig) -> RuntimeSelection:
        executable = Path(config.executable) if config.executable else None
        return RuntimeSelection(
            provider=config.provider,
            base_url=config.base_url,
            executable=executable,
            runtime_version=config.runtime_version,
        )

    def discover(
        self, config: Optional[BuddyConfig] = None
    ) -> Optional[RuntimeSelection]:
        if config:
            configured = self.selection_from_config(config)
            if self.api_is_ready(configured.base_url):
                return configured
            if configured.executable and configured.executable.exists():
                return configured

        if self.api_is_ready(DEFAULT_OLLAMA_BASE_URL):
            return RuntimeSelection(
                provider="system",
                base_url=DEFAULT_OLLAMA_BASE_URL,
                executable=self.find_system_executable(),
                runtime_version=None,
            )

        system_executable = self.find_system_executable()
        if system_executable:
            return RuntimeSelection(
                provider="system",
                base_url=DEFAULT_OLLAMA_BASE_URL,
                executable=system_executable,
                runtime_version=None,
            )

        managed_executable = self.find_managed_executable()
        if managed_executable:
            return RuntimeSelection(
                provider="managed",
                base_url=MANAGED_OLLAMA_BASE_URL,
                executable=managed_executable,
                runtime_version=OLLAMA_RUNTIME_VERSION,
            )
        return None
