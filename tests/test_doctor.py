"""Tests for Buddy diagnostics."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from buddy_cli.config import BuddyConfig, ConfigStore
from buddy_cli.doctor import Doctor
from buddy_cli.ollama import OllamaConnectionError, OllamaVersion
from buddy_cli.paths import AppPaths
from buddy_cli.runtime_manager import RuntimeManager


class HealthyClient:
    def __init__(self, base_url: str, timeout: float = 2.0) -> None:
        self.base_url = base_url

    def get_version(self) -> OllamaVersion:
        return OllamaVersion("0.32.5")

    def has_model(self, model: str) -> bool:
        return model == "test-model"


class OfflineClient:
    def __init__(self, base_url: str, timeout: float = 2.0) -> None:
        self.base_url = base_url

    def get_version(self) -> OllamaVersion:
        raise OllamaConnectionError("offline")


class DoctorTests(unittest.TestCase):
    def test_healthy_managed_installation_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = AppPaths(Path(temporary_directory))
            paths.ensure_directories()
            executable = paths.runtimes_dir / "ollama"
            executable.write_text("binary", encoding="utf-8")
            store = ConfigStore(paths)
            store.save(
                BuddyConfig(
                    provider="managed",
                    base_url="http://127.0.0.1:11435",
                    model="test-model",
                    executable=str(executable),
                    runtime_version="0.32.5",
                )
            )

            with patch("buddy_cli.doctor.OllamaClient", HealthyClient):
                report = Doctor(paths, store, RuntimeManager(paths)).run()

            self.assertTrue(report.healthy)
            self.assertTrue(
                any(
                    check.name == "model" and check.status == "PASS"
                    for check in report.checks
                )
            )

    def test_unconfigured_offline_installation_fails_with_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = AppPaths(Path(temporary_directory))

            with patch("buddy_cli.doctor.OllamaClient", OfflineClient):
                report = Doctor(
                    paths,
                    ConfigStore(paths),
                    RuntimeManager(paths),
                ).run()

            self.assertFalse(report.healthy)
            configuration = next(
                check for check in report.checks if check.name == "configuration"
            )
            self.assertIn("buddy setup", configuration.detail)
