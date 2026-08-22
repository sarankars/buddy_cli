"""Buddy installation diagnostics."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

from buddy_cli.config import BuddyConfig, ConfigError, ConfigStore
from buddy_cli.constants import DEFAULT_MODEL, DEFAULT_OLLAMA_BASE_URL
from buddy_cli.ollama import OllamaClient, OllamaError
from buddy_cli.paths import AppPaths
from buddy_cli.runtime_manager import RuntimeManager
from buddy_cli.runtime_manifest import resolve_runtime_spec


@dataclass(frozen=True)
class DiagnosticCheck:
    status: str
    name: str
    detail: str


@dataclass(frozen=True)
class DiagnosticReport:
    checks: List[DiagnosticCheck]

    @property
    def healthy(self) -> bool:
        return not any(check.status == "FAIL" for check in self.checks)

    def to_dict(self) -> Dict[str, object]:
        return {
            "healthy": self.healthy,
            "checks": [asdict(check) for check in self.checks],
        }


class Doctor:
    """Inspect Buddy without changing system or application state."""

    def __init__(
        self,
        paths: AppPaths,
        config_store: ConfigStore,
        runtime_manager: RuntimeManager,
    ) -> None:
        self.paths = paths
        self.config_store = config_store
        self.runtime_manager = runtime_manager

    def run(self) -> DiagnosticReport:
        checks: List[DiagnosticCheck] = []
        try:
            spec = resolve_runtime_spec()
            checks.append(
                DiagnosticCheck(
                    "PASS",
                    "platform",
                    f"managed runtime available for {spec.operating_system}/{spec.architecture}",
                )
            )
        except Exception as exc:
            checks.append(DiagnosticCheck("FAIL", "platform", str(exc)))

        writable_target = self.paths.root
        while (
            not writable_target.exists() and writable_target != writable_target.parent
        ):
            writable_target = writable_target.parent
        if os.access(writable_target, os.W_OK):
            checks.append(
                DiagnosticCheck(
                    "PASS",
                    "storage",
                    f"Buddy can write under {self.paths.root}",
                )
            )
        else:
            checks.append(
                DiagnosticCheck(
                    "FAIL",
                    "storage",
                    f"Buddy cannot write under {self.paths.root}",
                )
            )

        config: Optional[BuddyConfig]
        try:
            config = self.config_store.load()
            if config:
                checks.append(
                    DiagnosticCheck(
                        "PASS",
                        "configuration",
                        f"configured for {config.provider} Ollama",
                    )
                )
            else:
                checks.append(
                    DiagnosticCheck(
                        "FAIL",
                        "configuration",
                        "Buddy has not been set up; run 'buddy setup'",
                    )
                )
        except ConfigError as exc:
            config = None
            checks.append(DiagnosticCheck("FAIL", "configuration", str(exc)))

        if config and config.provider == "managed":
            executable = Path(config.executable) if config.executable else None
            if executable and executable.is_file():
                checks.append(DiagnosticCheck("PASS", "runtime", str(executable)))
            else:
                checks.append(
                    DiagnosticCheck(
                        "FAIL", "runtime", "managed Ollama executable is missing"
                    )
                )
        else:
            executable = self.runtime_manager.find_system_executable()
            checks.append(
                DiagnosticCheck(
                    "PASS" if executable else "WARN",
                    "runtime",
                    str(executable)
                    if executable
                    else "system Ollama executable not found",
                )
            )

        base_url = config.base_url if config else DEFAULT_OLLAMA_BASE_URL
        model = config.model if config else DEFAULT_MODEL
        try:
            client = OllamaClient(base_url, timeout=2.0)
            version = client.get_version()
            checks.append(
                DiagnosticCheck(
                    "PASS", "api", f"Ollama {version.version} at {base_url}"
                )
            )
            if client.has_model(model):
                checks.append(DiagnosticCheck("PASS", "model", model))
            else:
                checks.append(
                    DiagnosticCheck(
                        "FAIL", "model", f"{model} is not installed; run 'buddy setup'"
                    )
                )
        except (OllamaError, ValueError) as exc:
            checks.append(DiagnosticCheck("FAIL", "api", str(exc)))
            checks.append(
                DiagnosticCheck(
                    "WARN",
                    "model",
                    "model could not be checked while Ollama is offline",
                )
            )

        return DiagnosticReport(checks)
