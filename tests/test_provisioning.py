"""Tests for Buddy setup orchestration."""

import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import MagicMock, patch

from buddy_cli.config import ConfigStore
from buddy_cli.ollama import OllamaVersion
from buddy_cli.paths import AppPaths
from buddy_cli.provisioning import Provisioner, ProvisioningError, SetupCancelled
from buddy_cli.runtime_manager import RuntimeSelection


class FakeOllamaClient:
    def __init__(self, *, has_model: bool) -> None:
        self._has_model = has_model
        self.pulled = []
        self.generated = []

    def get_version(self) -> OllamaVersion:
        return OllamaVersion("0.32.5")

    def has_model(self, model: str) -> bool:
        return self._has_model

    def pull_model(self, model: str, *, progress=None) -> None:
        self.pulled.append(model)
        if progress:
            progress("success", None, None)

    def generate(self, model: str, prompt: str, *, system: str) -> str:
        self.generated.append((model, prompt, system))
        return "Say hello clearly."


class ProvisionerTests(unittest.TestCase):
    def test_reuses_system_runtime_and_downloads_missing_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = AppPaths(Path(temporary_directory))
            store = ConfigStore(paths)
            manager = MagicMock()
            selection = RuntimeSelection(
                provider="system",
                base_url="http://127.0.0.1:11434",
                executable=Path("/usr/local/bin/ollama"),
                runtime_version=None,
            )
            manager.discover.return_value = selection
            client = FakeOllamaClient(has_model=False)
            emitted = []

            with patch("buddy_cli.provisioning.OllamaClient", return_value=client):
                result = Provisioner(paths, store, manager).setup(
                    model="test-model",
                    confirm=lambda message, default: True,
                    emit=emitted.append,
                )

            self.assertFalse(result.installed_runtime)
            self.assertTrue(result.installed_model)
            self.assertEqual(client.pulled, ["test-model"])
            self.assertEqual(store.load().provider, "system")
            manager.start.assert_called_once_with(selection)

    def test_installs_managed_runtime_when_ollama_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = AppPaths(Path(temporary_directory))
            store = ConfigStore(paths)
            manager = MagicMock()
            manager.discover.return_value = None
            selection = RuntimeSelection(
                provider="managed",
                base_url="http://127.0.0.1:11435",
                executable=paths.runtimes_dir / "ollama",
                runtime_version="0.32.5",
            )
            manager.install_managed.return_value = selection
            client = FakeOllamaClient(has_model=True)

            with patch("buddy_cli.provisioning.OllamaClient", return_value=client):
                result = Provisioner(paths, store, manager).setup(
                    confirm=lambda message, default: True,
                    emit=lambda message: None,
                )

            self.assertTrue(result.installed_runtime)
            self.assertFalse(result.installed_model)
            manager.install_managed.assert_called_once()
            self.assertEqual(store.load().base_url, "http://127.0.0.1:11435")

    def test_declining_runtime_download_cancels_setup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = AppPaths(Path(temporary_directory))
            manager = MagicMock()
            manager.discover.return_value = None

            with self.assertRaises(SetupCancelled):
                Provisioner(paths, ConfigStore(paths), manager).setup(
                    confirm=lambda message, default: False,
                    emit=lambda message: None,
                )

            manager.install_managed.assert_not_called()

    def test_setup_stops_before_download_when_storage_is_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = AppPaths(Path(temporary_directory))
            manager = MagicMock()
            manager.discover.return_value = None
            usage = namedtuple("usage", "total used free")(100, 99, 1)

            with (
                patch("buddy_cli.provisioning.shutil.disk_usage", return_value=usage),
                self.assertRaises(ProvisioningError),
            ):
                Provisioner(paths, ConfigStore(paths), manager).setup(
                    confirm=lambda message, default: True,
                    emit=lambda message: None,
                )

            manager.install_managed.assert_not_called()
