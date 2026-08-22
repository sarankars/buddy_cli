# Releasing Buddy CLI

Buddy publishes GitHub Releases from strict, `v`-prefixed semantic-version tags.
Stable tags use the form `vMAJOR.MINOR.PATCH`; prereleases append a SemVer
identifier such as `v0.3.0-beta.1` or `v0.3.0-rc.2`.

## Prepare a release

1. Confirm the `main` branch quality workflow is green.
2. Update the base version in both `pyproject.toml` and
   `src/buddy_cli/__init__.py`. A prerelease such as `v0.3.0-beta.1` uses the
   base project version `0.3.0`.
3. Update documentation and commit the release-ready source to `main`.
4. Run the local checks:

   ```bash
   python -m ruff format --check src tests scripts
   python -m ruff check src tests scripts
   python -m unittest discover -s tests -v
   python -m pip check
   ```

5. Create and push an annotated tag that points to the verified commit:

   ```bash
   git tag -a v0.3.0 -m "Buddy CLI v0.3.0"
   git push origin v0.3.0
   ```

For a prerelease, use a tag such as `v0.3.0-beta.1`. Do not move or reuse a
published version tag.

## Automated release pipeline

Pushing a matching tag starts the `Release` workflow. It:

1. Rejects malformed SemVer tags and tags whose base version differs from the
   project version.
2. Runs the complete quality and test suite on Python 3.9 and 3.14.
3. Builds and smoke-tests native standalone binaries for macOS Intel and ARM64,
   Windows x64 and ARM64, and Linux x64 and ARM64.
4. Packages each executable and generates a SHA-256 checksum file.
5. Downloads all build artifacts into one final job, verifies the complete
   platform set and every checksum, and creates a combined `SHA256SUMS` file.
6. Creates a GitHub Release with generated release notes and attaches all six
   archives, six individual checksum files, and `SHA256SUMS`.

Tags containing a prerelease identifier are automatically published as GitHub
prereleases and are not marked as the latest stable release.

The publishing job depends on every validation, quality, and build job. If any
one fails, no GitHub Release is created. Fix the problem on `main`, choose the
next appropriate semantic version, and push a new tag. Normal pushes to `main`
only run the `Quality checks` workflow and never publish a release.

## Verify a downloaded archive

On Linux:

```bash
sha256sum --check buddy-linux-x64.tar.gz.sha256
```

On macOS:

```bash
shasum -a 256 --check buddy-macos-arm64.tar.gz.sha256
```
