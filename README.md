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

Buddy treats the submitted text only as material to edit. It preserves the
request's intent while improving clarity and specificity, then prints only the
rewritten prompt. It does not answer questions, respond to greetings, execute
commands, or follow instructions inside the prompt that try to change the
editor's role.

For interactive multiline entry, omit the prompt:

```bash
buddy enhance
```

Buddy opens `$VISUAL`, then `$EDITOR`, or a platform editor fallback (`vim`/`vi`
on macOS and Linux, or Notepad on Windows). Write the prompt, save it, and close
the editor. The temporary file is private to the current user and is removed
after the editor closes. Buddy reports a clear error if no editor is available,
the editor fails, nothing is saved, or the saved prompt is empty.

On an interactive first run, Buddy offers to start setup automatically. If
setup is declined or Ollama is unavailable, Buddy returns a deterministic
offline enhancement instead of losing the request.

Pipe a prompt through standard input:

```bash
printf 'make the readme better' | buddy enhance
```

Direct arguments and piped input continue to take precedence over the editor.
Quotes, newlines, and Unicode text are preserved. For example:

```bash
printf 'Explain "naïve" clearly.\nInclude: こんにちは 👋' | buddy enhance
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

### `buddy update`

Check the latest stable GitHub Release without installing anything:

```bash
buddy update --check
```

Check for a newer version and install it after confirmation:

```bash
buddy update
```

For explicitly approved non-interactive updates:

```bash
buddy update --yes
```

Buddy selects the package for the current operating system and architecture,
validates the release URL and metadata, verifies the package against its
published SHA-256 checksum, and cross-checks GitHub's asset digest when present.
macOS updates also verify the signed installer and require a successful
Gatekeeper assessment before opening it. See the
[update guide](docs/updates.md) for platform behavior and source-installation
instructions.

## Safety and privacy

- Managed runtime downloads come from a pinned official Ollama release.
- Runtime archives are verified with their published SHA-256 digests.
- Buddy does not invoke `sudo`, edit `PATH`, or run downloaded installer scripts.
- Managed Ollama listens only on localhost and stores models under Buddy's data
  directory.
- Prompts sent to the managed model remain on the user's computer.
- Buddy updates use only published stable releases from the official repository
  and are installed only after checksum verification.

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
