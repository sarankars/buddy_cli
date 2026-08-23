# Updating Buddy CLI

Buddy's standalone executable can check the latest stable release and install a
newer version for the current platform.

## Commands

Check without downloading or changing anything:

```bash
buddy update --check
```

Check and ask before installing an available update:

```bash
buddy update
```

Approve installation in a non-interactive environment:

```bash
buddy update --yes
```

Without `--yes`, Buddy refuses to install from redirected or otherwise
non-interactive input because it cannot obtain confirmation. Prereleases and
draft releases are never selected by this command.

## Verification

Buddy retrieves the latest stable release metadata from the public GitHub API
and requires asset URLs to belong to `sarankars/buddy_cli`. It selects exactly
one package and its matching `.sha256` file for the current operating system and
architecture. Before installation, Buddy:

1. Validates the checksum file's format and filename.
2. Cross-checks the checksum against GitHub's asset digest when the API provides
   one.
3. Downloads the package to Buddy's application-data directory.
4. Verifies the complete package with SHA-256.
5. Rejects executable archives containing unexpected entries, links, or paths.
6. Runs the downloaded executable and verifies its reported version before
   replacement on Linux and Windows.

## Platform behavior

### macOS

Official releases use Developer ID-signed and Apple-notarized installer
packages. Buddy verifies the package signature, requires a successful macOS
Gatekeeper assessment, and invokes `/usr/sbin/installer` directly so the
graphical Next/Install flow is not required. Installing into `/usr/local/bin`
still requires administrator permissions. Buddy verifies the version installed
at `/usr/local/bin/buddy` after installation.

### Linux

Buddy stages and smoke-tests the new executable, writes it into the current
executable's directory, and atomically replaces the old executable. The current
directory must be writable by the user running the update. Restart Buddy after
the command completes.

### Windows

Windows does not allow a running executable to replace itself. Buddy
smoke-tests the downloaded executable and starts a detached PowerShell helper
that waits for the current Buddy process to exit before replacing it. Start
Buddy again after a few seconds. The installation directory must be writable.

## Source installations

`buddy update --check` works from a source checkout, but automatic installation
is intentionally limited to standalone Buddy binaries. For a source build,
update with `cargo install --path . --locked` after fetching the new version.
