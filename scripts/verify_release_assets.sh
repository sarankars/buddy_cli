#!/usr/bin/env bash
# Verify all platform release archives and their SHA-256 checksums.
# Writes a combined SHA256SUMS file into the asset directory.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <release-assets-dir>" >&2
  exit 1
fi

DIR="$1"
if [[ ! -d "$DIR" ]]; then
  echo "error: directory does not exist: $DIR" >&2
  exit 1
fi

ARCHIVES=(
  "buddy-linux-arm64.tar.gz"
  "buddy-linux-x64.tar.gz"
  "buddy-macos-arm64.pkg"
  "buddy-macos-x64.pkg"
  "buddy-windows-arm64.zip"
  "buddy-windows-x64.zip"
)

EXPECTED_FILES=()
for name in "${ARCHIVES[@]}"; do
  EXPECTED_FILES+=("$name" "${name}.sha256")
done

# Check for missing files
MISSING=()
for f in "${EXPECTED_FILES[@]}"; do
  [[ -f "$DIR/$f" ]] || MISSING+=("$f")
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "error: missing release assets: ${MISSING[*]}" >&2
  exit 1
fi

# Check for unexpected files
ACTUAL_FILES=()
while IFS= read -r -d '' f; do
  ACTUAL_FILES+=("$(basename "$f")")
done < <(find "$DIR" -maxdepth 1 -type f -print0 | sort -z)

for f in "${ACTUAL_FILES[@]}"; do
  found=0
  for expected in "${EXPECTED_FILES[@]}"; do
    [[ "$f" == "$expected" ]] && found=1 && break
  done
  if [[ $found -eq 0 ]]; then
    echo "error: unexpected release asset: $f" >&2
    exit 1
  fi
done

# Verify each checksum and build combined file
COMBINED="$DIR/SHA256SUMS"
: > "$COMBINED"

for archive_name in "${ARCHIVES[@]}"; do
  archive="$DIR/$archive_name"
  checksum_file="$DIR/${archive_name}.sha256"

  # shasum is available on macOS; sha256sum on Linux
  if command -v sha256sum &>/dev/null; then
    actual_line=$(sha256sum "$archive" | sed 's|.*/||')
  else
    actual_line=$(shasum -a 256 "$archive" | sed 's|.*/||')
  fi

  stored=$(cat "$checksum_file")
  # Normalise line endings
  stored="${stored//$'\r'/}"

  if [[ "$actual_line" != "$stored" ]]; then
    echo "error: checksum verification failed for $archive_name" >&2
    echo "  expected: $stored" >&2
    echo "  actual:   $actual_line" >&2
    exit 1
  fi

  echo "$actual_line" >> "$COMBINED"
done

echo "$COMBINED"
