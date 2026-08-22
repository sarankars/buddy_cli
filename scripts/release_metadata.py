"""Validate a release tag and emit GitHub Actions metadata."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import Optional, Sequence

_NUMBER = r"(?:0|[1-9][0-9]*)"
_NON_NUMERIC_IDENTIFIER = r"(?:[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
_PRERELEASE_IDENTIFIER = rf"(?:{_NUMBER}|{_NON_NUMERIC_IDENTIFIER})"
SEMVER_TAG = re.compile(
    rf"^v(?P<version>{_NUMBER}\.{_NUMBER}\.{_NUMBER})"
    rf"(?:-(?P<prerelease>{_PRERELEASE_IDENTIFIER}"
    rf"(?:\.{_PRERELEASE_IDENTIFIER})*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class ReleaseTagError(ValueError):
    """Raised when a release tag is not valid for Buddy."""


@dataclass(frozen=True)
class ReleaseMetadata:
    tag: str
    version: str
    prerelease: bool


def parse_release_tag(
    tag: str, project_version: Optional[str] = None
) -> ReleaseMetadata:
    """Parse strict v-prefixed SemVer and optionally match the project version."""
    match = SEMVER_TAG.fullmatch(tag)
    if match is None:
        raise ReleaseTagError(
            f"release tag must be strict SemVer such as v0.3.0 or "
            f"v0.3.0-beta.1: {tag!r}"
        )

    version = match.group("version")
    if project_version is not None and version != project_version:
        raise ReleaseTagError(
            f"tag version {version} does not match project version {project_version}"
        )
    return ReleaseMetadata(tag, version, match.group("prerelease") is not None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="v-prefixed semantic-version tag")
    parser.add_argument(
        "--project-version",
        required=True,
        help="Buddy's base project version, without the v prefix",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        metadata = parse_release_tag(args.tag, args.project_version)
    except ReleaseTagError as exc:
        parser.error(str(exc))
    print(f"tag={metadata.tag}")
    print(f"version={metadata.version}")
    print(f"prerelease={'true' if metadata.prerelease else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
