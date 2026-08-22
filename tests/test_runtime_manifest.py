"""Tests for the pinned Ollama runtime manifest."""

import unittest

from buddy_cli.runtime_manifest import (
    UnsupportedPlatformError,
    format_bytes,
    resolve_runtime_spec,
)


class RuntimeManifestTests(unittest.TestCase):
    def test_resolves_supported_platform_aliases(self) -> None:
        mac = resolve_runtime_spec(platform_name="darwin", machine="x86_64")
        windows = resolve_runtime_spec(platform_name="win32", machine="ARM64")
        linux = resolve_runtime_spec(platform_name="linux", machine="aarch64")

        self.assertEqual(mac.architecture, "amd64")
        self.assertEqual(windows.architecture, "arm64")
        self.assertEqual(linux.asset_name, "ollama-linux-arm64.tar.zst")

    def test_rejects_unsupported_platform(self) -> None:
        with self.assertRaises(UnsupportedPlatformError):
            resolve_runtime_spec(platform_name="plan9", machine="mips")

    def test_formats_download_sizes(self) -> None:
        self.assertEqual(format_bytes(1_900_000_000), "1.9 GB")
