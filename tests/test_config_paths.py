"""Tests for Buddy application paths and configuration."""

import json
import tempfile
import unittest
from pathlib import Path

from buddy_cli.config import BuddyConfig, ConfigError, ConfigStore
from buddy_cli.paths import AppPaths


class AppPathsTests(unittest.TestCase):
    def test_environment_override_wins_on_every_platform(self) -> None:
        paths = AppPaths.discover(
            platform_name="win32",
            environment={"BUDDY_HOME": "/tmp/buddy-test"},
            home=Path("/unused"),
        )

        self.assertEqual(paths.root, Path("/tmp/buddy-test"))

    def test_platform_defaults(self) -> None:
        home = Path("/Users/example")

        mac = AppPaths.discover(platform_name="darwin", environment={}, home=home)
        linux = AppPaths.discover(platform_name="linux", environment={}, home=home)

        self.assertEqual(mac.root, home / "Library" / "Application Support" / "Buddy")
        self.assertEqual(linux.root, home / ".local" / "share" / "buddy")

    def test_ensure_directories_creates_update_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = AppPaths(Path(temporary_directory) / "buddy")

            paths.ensure_directories()

            self.assertTrue(paths.updates_dir.is_dir())


class ConfigStoreTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = ConfigStore(AppPaths(Path(temporary_directory)))
            expected = BuddyConfig(
                provider="managed",
                base_url="http://127.0.0.1:11435",
                model="test-model",
                executable="/tmp/ollama",
                runtime_version="1.0.0",
            )

            store.save(expected)

            self.assertEqual(store.load(), expected)

    def test_invalid_provider_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = AppPaths(Path(temporary_directory))
            paths.ensure_directories()
            paths.config_file.write_text(
                json.dumps(
                    {
                        "provider": "unknown",
                        "base_url": "http://127.0.0.1:11434",
                        "model": "test-model",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                ConfigStore(paths).load()
