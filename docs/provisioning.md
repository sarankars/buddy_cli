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
