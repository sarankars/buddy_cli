"""Platform-specific application paths."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional


@dataclass(frozen=True)
class AppPaths:
    """Filesystem locations owned by Buddy."""

    root: Path

    @property
    def config_file(self) -> Path:
        return self.root / "config.json"

    @property
    def runtimes_dir(self) -> Path:
        return self.root / "runtimes"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def downloads_dir(self) -> Path:
        return self.root / "downloads"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def ollama_log_file(self) -> Path:
        return self.logs_dir / "ollama.log"

    @property
    def ollama_pid_file(self) -> Path:
        return self.root / "ollama.pid"

    def ensure_directories(self) -> None:
        for path in (
            self.root,
            self.runtimes_dir,
            self.models_dir,
            self.downloads_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @classmethod
    def discover(
        cls,
        *,
        platform_name: Optional[str] = None,
        environment: Optional[Mapping[str, str]] = None,
        home: Optional[Path] = None,
    ) -> "AppPaths":
        env = environment if environment is not None else os.environ
        override = env.get("BUDDY_HOME")
        if override:
            return cls(Path(override).expanduser())

        current_platform = platform_name or sys.platform
        user_home = home or Path.home()

        if current_platform == "darwin":
            root = user_home / "Library" / "Application Support" / "Buddy"
        elif current_platform == "win32":
            local_app_data = env.get("LOCALAPPDATA")
            root = (
                Path(local_app_data) / "Buddy"
                if local_app_data
                else user_home / "AppData" / "Local" / "Buddy"
            )
        else:
            xdg_data_home = env.get("XDG_DATA_HOME")
            root = (
                Path(xdg_data_home) / "buddy"
                if xdg_data_home
                else user_home / ".local" / "share" / "buddy"
            )

        return cls(root)
