"""Safe extraction for pinned runtime archives."""

from __future__ import annotations

import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


class ArchiveError(RuntimeError):
    """Raised when an archive is unsupported or unsafe."""


def _safe_member_path(root: Path, member_name: str) -> Path:
    member = PurePosixPath(member_name.replace("\\", "/"))
    if member.is_absolute() or ".." in member.parts:
        raise ArchiveError(f"archive contains an unsafe path: {member_name}")
    if member.parts and ":" in member.parts[0]:
        raise ArchiveError(f"archive contains an unsafe path: {member_name}")

    root_resolved = root.resolve()
    target = root.joinpath(*member.parts).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise ArchiveError(f"archive path escapes destination: {member_name}") from exc
    return target


def _extract_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            _safe_member_path(destination, member.filename)
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ArchiveError("symbolic links are not allowed in ZIP archives")
        bundle.extractall(destination)


def _validate_tar_member(destination: Path, member: tarfile.TarInfo) -> None:
    target = _safe_member_path(destination, member.name)
    if member.ischr() or member.isblk() or member.isfifo():
        raise ArchiveError(f"archive contains a special device: {member.name}")
    if member.issym():
        link_target = (target.parent / member.linkname).resolve()
        try:
            link_target.relative_to(destination.resolve())
        except ValueError as exc:
            raise ArchiveError(
                f"archive link escapes destination: {member.name}"
            ) from exc
    elif member.islnk():
        _safe_member_path(destination, member.linkname)


def _extract_tar(bundle: tarfile.TarFile, destination: Path) -> None:
    for member in bundle:
        _validate_tar_member(destination, member)
        bundle.extract(member, destination)


def extract_archive(archive: Path, destination: Path, archive_type: str) -> None:
    """Safely extract a supported runtime archive."""
    destination.mkdir(parents=True, exist_ok=True)
    if archive_type == "zip":
        _extract_zip(archive, destination)
        return

    if archive_type == "tgz":
        with tarfile.open(archive, mode="r:gz") as bundle:
            _extract_tar(bundle, destination)
        return

    if archive_type == "tar.zst":
        try:
            import zstandard
        except ImportError as exc:
            raise ArchiveError(
                "zstandard is required to extract the Linux Ollama runtime"
            ) from exc

        decompressor = zstandard.ZstdDecompressor()
        with (
            archive.open("rb") as source,
            decompressor.stream_reader(source) as reader,
            tarfile.open(fileobj=reader, mode="r|") as bundle,
        ):
            _extract_tar(bundle, destination)
        return

    raise ArchiveError(f"unsupported archive type: {archive_type}")
