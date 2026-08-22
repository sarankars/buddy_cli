"""Persistent Buddy configuration."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from buddy_cli.constants import CONFIG_SCHEMA_VERSION
from buddy_cli.paths import AppPaths


class ConfigError(ValueError):
    """Raised when Buddy configuration is invalid or unreadable."""


@dataclass(frozen=True)
class BuddyConfig:
    """A verified local enhancement configuration."""

    provider: str
    base_url: str
    model: str
    executable: Optional[str] = None
    runtime_version: Optional[str] = None
    schema_version: int = CONFIG_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "BuddyConfig":
        required_strings = ("provider", "base_url", "model")
        for key in required_strings:
            if not isinstance(value.get(key), str) or not value[key].strip():
                raise ConfigError(f"configuration field '{key}' must be a string")

        schema_version = value.get("schema_version", CONFIG_SCHEMA_VERSION)
        if schema_version != CONFIG_SCHEMA_VERSION:
            raise ConfigError(
                f"unsupported configuration schema version: {schema_version}"
            )

        provider = value["provider"]
        if provider not in {"managed", "system"}:
            raise ConfigError(f"unsupported Ollama provider: {provider}")

        executable = value.get("executable")
        runtime_version = value.get("runtime_version")
        if executable is not None and not isinstance(executable, str):
            raise ConfigError("configuration field 'executable' must be a string")
        if runtime_version is not None and not isinstance(runtime_version, str):
            raise ConfigError("configuration field 'runtime_version' must be a string")

        return cls(
            provider=provider,
            base_url=value["base_url"],
            model=value["model"],
            executable=executable,
            runtime_version=runtime_version,
            schema_version=schema_version,
        )


class ConfigStore:
    """Read and atomically write Buddy configuration."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def load(self) -> Optional[BuddyConfig]:
        if not self.paths.config_file.exists():
            return None

        try:
            with self.paths.config_file.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"could not read Buddy configuration: {exc}") from exc

        if not isinstance(value, dict):
            raise ConfigError("Buddy configuration must contain a JSON object")
        return BuddyConfig.from_dict(value)

    def save(self, config: BuddyConfig) -> None:
        self.paths.ensure_directories()
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".config-",
            suffix=".json",
            dir=str(self.paths.root),
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(asdict(config), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(str(temporary_path), str(self.paths.config_file))
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
