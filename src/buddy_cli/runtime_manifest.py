"""Pinned Ollama runtime artifacts supported by Buddy."""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from buddy_cli.constants import OLLAMA_RUNTIME_VERSION


class UnsupportedPlatformError(RuntimeError):
    """Raised when no managed Ollama artifact matches the current machine."""


@dataclass(frozen=True)
class RuntimeSpec:
    """A pinned, checksum-verified Ollama release artifact."""

    operating_system: str
    architecture: str
    asset_name: str
    sha256: str
    size: int
    archive_type: str
    version: str = OLLAMA_RUNTIME_VERSION

    @property
    def url(self) -> str:
        return (
            "https://github.com/ollama/ollama/releases/download/"
            f"v{self.version}/{self.asset_name}"
        )

    @property
    def installation_name(self) -> str:
        return f"ollama-{self.version}-{self.operating_system}-{self.architecture}"


_SPECS: Dict[Tuple[str, str], RuntimeSpec] = {}


def _register(
    operating_system: str,
    architectures: Tuple[str, ...],
    asset_name: str,
    sha256: str,
    size: int,
    archive_type: str,
) -> None:
    for architecture in architectures:
        _SPECS[(operating_system, architecture)] = RuntimeSpec(
            operating_system=operating_system,
            architecture=architecture,
            asset_name=asset_name,
            sha256=sha256,
            size=size,
            archive_type=archive_type,
        )


_register(
    "darwin",
    ("arm64", "amd64"),
    "ollama-darwin.tgz",
    "5789dd037a86adb328c72c11fc45e6c558452d07e5b50814a8bdb7b0fbdbcd81",
    145_747_028,
    "tgz",
)
_register(
    "linux",
    ("amd64",),
    "ollama-linux-amd64.tar.zst",
    "f7d6bdbcf71b83aa8670c4e7dc4b6936c0952fcf8b114eaf6a11cbadb9684214",
    1_422_353_729,
    "tar.zst",
)
_register(
    "linux",
    ("arm64",),
    "ollama-linux-arm64.tar.zst",
    "aa7e06b5683ee66c4a3ec68ea7236db43b5a5d0821f0dfe2c5a215f4462bddf4",
    1_542_011_985,
    "tar.zst",
)
_register(
    "windows",
    ("amd64",),
    "ollama-windows-amd64.zip",
    "7c941ae084569d298062d29f8139163a3187c76dbca0479c70d085e78fd8c7bb",
    1_457_824_795,
    "zip",
)
_register(
    "windows",
    ("arm64",),
    "ollama-windows-arm64.zip",
    "f7cf76916c24550033500a92fb56b3ce3d225f3d7cde0ce0438e62696b34507a",
    209_422_558,
    "zip",
)


def normalize_operating_system(value: str) -> str:
    lowered = value.lower()
    if lowered == "win32" or lowered.startswith("windows"):
        return "windows"
    if lowered.startswith("darwin") or lowered.startswith("mac"):
        return "darwin"
    if lowered.startswith("linux"):
        return "linux"
    return lowered


def normalize_architecture(value: str) -> str:
    lowered = value.lower()
    if lowered in {"x86_64", "x64", "amd64"}:
        return "amd64"
    if lowered in {"aarch64", "arm64"}:
        return "arm64"
    return lowered


def resolve_runtime_spec(
    *,
    platform_name: Optional[str] = None,
    machine: Optional[str] = None,
) -> RuntimeSpec:
    operating_system = normalize_operating_system(platform_name or sys.platform)
    architecture = normalize_architecture(machine or platform.machine())
    spec = _SPECS.get((operating_system, architecture))
    if spec is None:
        raise UnsupportedPlatformError(
            f"managed Ollama is not available for {operating_system}/{architecture}"
        )
    return spec


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1000
    return f"{size:.1f} TB"
