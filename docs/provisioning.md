# Buddy provisioning design

Buddy provides three user-facing commands:

- `buddy setup` provisions and verifies the local enhancement runtime.
- `buddy enhance` improves a rough prompt and can offer setup on first use.
- `buddy doctor` explains whether Buddy is ready and how to repair it.

## Provisioning guarantees

Buddy follows these rules when it provisions Ollama and the enhancement model:

1. Reuse a healthy system Ollama service when one already exists.
2. Never overwrite an existing system installation.
3. Ask before downloading a runtime or model.
4. Download runtime archives only from the pinned official Ollama release.
5. Verify every runtime archive with its published SHA-256 digest.
6. Keep managed files inside Buddy's application-data directory.
7. Never invoke `sudo`, modify `PATH`, or execute a downloaded installer script.
8. Bind a managed Ollama service to localhost on a Buddy-specific port.
9. Resume runtime downloads after transient failures and remove unsafe or
   checksum-mismatched files.
10. Fall back to the deterministic offline enhancer when local AI is unavailable.

## Prompt input and editing contract

`buddy enhance "prompt"` enhances its command arguments, while redirected
standard input is read when no arguments are present. On an interactive terminal
with neither source, Buddy opens `$VISUAL`, then `$EDITOR`, and finally a
platform-appropriate fallback. Editor input is collected in a private temporary
file that is removed after use, including when the editor fails.

The local model receives the original prompt as JSON-encoded, untrusted editing
material. A system instruction restricts it to prompt editing, structured output
constrains the response shape, and deterministic generation settings reduce
variation. Buddy validates the response and retries once when the model emits an
answer, conversational reply, malformed structure, or empty rewrite. A second
invalid response is discarded and the existing deterministic enhancer is used.

## First-run flow

```text
buddy setup
  -> detect platform and existing Ollama
  -> obtain download consent if a managed runtime is needed
  -> download, verify, and extract the runtime
  -> start the local API
  -> obtain download consent if the model is missing
  -> pull the model with progress
  -> run a generation smoke test
  -> save the verified configuration
```

Running `buddy setup` repeatedly is safe. Completed downloads and compatible
installations are reused.

## Managed locations

- macOS: `~/Library/Application Support/Buddy`
- Windows: `%LOCALAPPDATA%\Buddy`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/buddy`

`BUDDY_HOME` can override the data directory for development and testing.

## Runtime and model policy

Buddy pins a tested Ollama release rather than downloading an untested latest
release. Runtime URLs, sizes, and SHA-256 digests are part of Buddy's release.
The default model is `qwen2.5:3b-instruct`.

Buddy-managed Ollama uses a private model directory and listens on
`127.0.0.1:11435`. A compatible system Ollama continues to use its own model
directory and the default `127.0.0.1:11434` endpoint.
