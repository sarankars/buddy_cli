# Releasing Buddy CLI

Buddy publishes GitHub Releases from strict, `v`-prefixed semantic-version tags.
Stable tags use the form `vMAJOR.MINOR.PATCH`; prereleases append a SemVer
identifier such as `v0.3.0-beta.1` or `v0.3.0-rc.2`.

## Apple release credentials

macOS releases require an active Apple Developer Program membership. The Apple
Account Holder must create and export these certificates with their private
keys as password-protected PKCS#12 (`.p12`) files:

- Developer ID Application
- Developer ID Installer

Configure these GitHub Actions repository secrets before pushing a release tag:

- `APPLE_DEVELOPER_ID_APPLICATION_P12_BASE64`
- `APPLE_DEVELOPER_ID_APPLICATION_P12_PASSWORD`
- `APPLE_DEVELOPER_ID_INSTALLER_P12_BASE64`
- `APPLE_DEVELOPER_ID_INSTALLER_P12_PASSWORD`
- `APPLE_ID`
- `APPLE_TEAM_ID`
- `APPLE_APP_SPECIFIC_PASSWORD`

Encode each certificate without modifying the original file:

```bash
base64 -i developer-id-application.p12 | pbcopy
```

Paste the result directly into the matching GitHub secret. Repeat for the
installer certificate. Never commit certificates, private keys, certificate
passwords, Apple IDs, or app-specific passwords to the repository.

See Apple's guides for
[Developer ID certificates](https://developer.apple.com/help/account/certificates/create-developer-id-certificates)
and
[custom notarization](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow),
and GitHub's guide to
[installing Apple certificates on macOS runners](https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms/sign-xcode-applications).

## Prepare a release

1. Confirm the `main` branch quality workflow is green.
2. Update the version in `Cargo.toml`. A prerelease such as `v0.3.0-beta.1`
   uses the base project version `0.3.0`.
3. Update documentation and commit the release-ready source to `main`.
4. Run the local checks:

   ```bash
   cargo fmt --check
   cargo clippy --all-targets -- -D warnings
   cargo test
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
2. Runs the complete Rust quality and test suite.
3. Builds and smoke-tests native standalone binaries for macOS Intel and ARM64,
   Windows x64 and ARM64, and Linux x64 and ARM64.
4. Signs every macOS executable with Developer ID Application, creates a signed
   installer package, submits it to Apple's notary service, staples the accepted
   ticket, and verifies it with `pkgutil`, `stapler`, and `spctl`.
5. Packages every platform and generates a SHA-256 checksum only after all
   signing and notarization mutations are complete.
6. Downloads all build artifacts into one final job, verifies the complete
   platform set and every checksum, and creates a combined `SHA256SUMS` file.
7. Creates a GitHub Release with generated release notes and attaches all six
   platform packages, six individual checksum files, and `SHA256SUMS`.

Tags containing a prerelease identifier are automatically published as GitHub
prereleases and are not marked as the latest stable release.

The publishing job depends on every validation, quality, build, signing, and
notarization job. Missing Apple secrets, rejected notarization, unstapled
tickets, invalid signatures, or any other failure prevent creation of the
GitHub Release. Fix the problem on `main`, choose the next appropriate semantic
version, and push a new tag. Normal pushes to `main` only run the `Quality
checks` workflow and never publish a release.

## Verify a downloaded archive

On Linux:

```bash
sha256sum --check buddy-linux-x64.tar.gz.sha256
```

On macOS:

```bash
shasum -a 256 --check buddy-macos-arm64.pkg.sha256
pkgutil --check-signature buddy-macos-arm64.pkg
spctl --assess --type install --verbose=4 buddy-macos-arm64.pkg
```
