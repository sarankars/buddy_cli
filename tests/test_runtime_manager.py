"""Tests for Buddy-managed Ollama runtime installation."""

import hashlib
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from buddy_cli.paths import AppPaths
from buddy_cli.runtime_manager import RuntimeManager
from buddy_cli.runtime_manifest import RuntimeSpec


class RuntimeManagerTests(unittest.TestCase):
    def test_installs_and_reuses_verified_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_directory = root / "source"
            source_directory.mkdir()
            executable = source_directory / "ollama"
            executable.write_bytes(b"runtime")
            source_archive = root / "source.tgz"
            with tarfile.open(source_archive, "w:gz") as bundle:
                bundle.add(executable, arcname="bin/ollama")
            digest = hashlib.sha256(source_archive.read_bytes()).hexdigest()
            spec = RuntimeSpec(
                operating_system="darwin",
                architecture="arm64",
                asset_name="test-runtime.tgz",
                sha256=digest,
                size=source_archive.stat().st_size,
                archive_type="tgz",
                version="test",
            )
            paths = AppPaths(root / "buddy-data")
            manager = RuntimeManager(paths)
            downloads = []

            def fake_download(url, destination, expected_sha256, **kwargs):
                downloads.append(url)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_archive, destination)
                return destination

            with (
                patch(
                    "buddy_cli.runtime_manager.resolve_runtime_spec",
                    return_value=spec,
                ),
                patch(
                    "buddy_cli.runtime_manager.download_verified",
                    side_effect=fake_download,
                ),
            ):
                first = manager.install_managed()
                second = manager.install_managed()

            self.assertTrue(first.executable.is_file())
            self.assertEqual(first, second)
            self.assertEqual(len(downloads), 1)
