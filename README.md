# Buddy CLI

Buddy improves rough prompts before they are sent to an AI assistant. It uses a
local Ollama model when configured and retains a deterministic offline enhancer
when local AI is unavailable.

## Commands

### `buddy setup`

Provision and verify Ollama and the prompt-enhancement model:

```bash
buddy setup
```

Buddy reuses a healthy system Ollama service when possible. Otherwise it asks
permission to download a pinned, checksum-verified runtime into Buddy's private
application-data directory. It then asks before downloading the default
`qwen2.5:3b-instruct` model, runs an enhancement smoke test, and saves the
verified configuration.

Runtime downloads show transfer speed and an estimated completion time. If the
connection stalls, Buddy retries automatically and preserves the partial file so
the next `buddy setup` continues instead of starting over.

For unattended environments, explicitly approve downloads:

```bash
buddy setup --yes
```

Preview setup without making changes:

```bash
buddy setup --dry-run
```

### `buddy enhance`

Enhance a prompt with the configured local model:

```bash
buddy enhance "make the readme better"
```

On an interactive first run, Buddy offers to start setup automatically. If
setup is declined or Ollama is unavailable, Buddy returns a deterministic
offline enhancement instead of losing the request.

Pipe a prompt through standard input:

```bash
printf 'make the readme better' | buddy enhance
```

Force the offline enhancer:

```bash
buddy enhance --offline "make the readme better"
```

### `buddy doctor`

Check platform support, storage access, configuration, the Ollama runtime, its
local API, and the configured model:

```bash
buddy doctor
buddy doctor --json
```

## Safety and privacy

- Managed runtime downloads come from a pinned official Ollama release.
- Runtime archives are verified with their published SHA-256 digests.
- Buddy does not invoke `sudo`, edit `PATH`, or run downloaded installer scripts.
- Managed Ollama listens only on localhost and stores models under Buddy's data
  directory.
- Prompts sent to the managed model remain on the user's computer.

See [the provisioning design](docs/provisioning.md) for the complete behavior
and platform-specific storage locations.

## Development

Buddy requires Python 3.9 or newer for source development.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --editable .
python -m unittest discover -s tests -v
```

`BUDDY_HOME` overrides the application-data directory for isolated development
and tests:

```bash
BUDDY_HOME=/tmp/buddy-dev buddy setup --dry-run
```

## Standalone executable

Install the build dependency and create a platform-specific executable:

```bash
python -m pip install --editable '.[build]'
python scripts/build_standalone.py
```

The result is written to `dist/buddy` (`dist/buddy.exe` on Windows). The
executable includes Python and Buddy's Python dependencies. Ollama and the model
remain first-run downloads managed by `buddy setup`, keeping the Buddy download
itself reasonably small.

Official macOS releases are Developer ID-signed, notarized, and distributed as
installer packages. Download the package matching the Mac's architecture and
open it, or install it from Terminal:

```bash
sudo installer -pkg buddy-macos-arm64.pkg -target /
buddy --version
```

The package installs `buddy` in `/usr/local/bin` and carries a stapled Apple
notarization ticket for Gatekeeper verification.

## GitHub Actions

Every push to `main` runs the test suite on the minimum supported Python version
and the latest stable Python version, along with formatting, lint, compilation,
and dependency checks.

Pushing a matching semantic-version tag builds and smoke-tests standalone
packages for macOS Intel and ARM64, Windows x64 and ARM64, and Linux x64 and
ARM64. The macOS packages must pass Developer ID signing, Apple notarization,
ticket stapling, and Gatekeeper assessment. After every job succeeds, GitHub
Actions verifies SHA-256 checksums and publishes the packages and checksums in a
GitHub Release. See the
[maintainer release guide](docs/releases.md) for the complete process.
