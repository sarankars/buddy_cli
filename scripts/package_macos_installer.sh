#!/usr/bin/env bash
# Create a signed macOS PKG installer that places Buddy into /usr/local/bin.
set -euo pipefail

usage() {
  echo "Usage: $0 --target <macos-x64|macos-arm64> --version <X.Y.Z> --signing-identity <identity> [--binary <path>]"
  exit 1
}

TARGET=""
VERSION=""
IDENTITY=""
BINARY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)           TARGET="$2";   shift 2 ;;
    --version)          VERSION="$2";  shift 2 ;;
    --signing-identity) IDENTITY="$2"; shift 2 ;;
    --binary)           BINARY="$2";   shift 2 ;;
    *) usage ;;
  esac
done

[[ -z "$TARGET" || -z "$VERSION" || -z "$IDENTITY" ]] && usage

if [[ ! "$TARGET" =~ ^macos-(arm64|x64)$ ]]; then
  echo "error: target must be macos-arm64 or macos-x64" >&2
  exit 1
fi

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "error: version must be X.Y.Z" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -z "$BINARY" ]]; then
  BINARY="$REPO_ROOT/dist/buddy"
fi

if [[ ! -f "$BINARY" ]]; then
  echo "error: binary does not exist: $BINARY" >&2
  exit 1
fi

RELEASE_DIR="$REPO_ROOT/release"
mkdir -p "$RELEASE_DIR"
ARCHIVE="$RELEASE_DIR/buddy-${TARGET}.pkg"

TMPDIR="$(mktemp -d -t buddy-pkg)"
trap 'rm -rf "$TMPDIR"' EXIT

PKG_ROOT="$TMPDIR/root"
INSTALL_DIR="$PKG_ROOT/usr/local/bin"
mkdir -p "$INSTALL_DIR"
cp -p "$BINARY" "$INSTALL_DIR/buddy"
chmod 0755 "$INSTALL_DIR/buddy"

pkgbuild \
  --root "$PKG_ROOT" \
  --install-location "/" \
  --identifier "com.sarankars.buddy-cli" \
  --version "$VERSION" \
  --ownership recommended \
  --sign "$IDENTITY" \
  "$ARCHIVE"

echo "$ARCHIVE"
