# Buddy CLI

Buddy is a small Python CLI foundation for improving rough prompts before they
are passed to an AI assistant.

The initial version provides a deterministic, offline enhancer. It trims the
input and wraps it with instructions that preserve the user's intent, make
reasonable assumptions explicit, and request an actionable result. It does not
call an AI model yet.

## Requirements

- Python 3.9 or newer

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --editable .
```

## Usage

Pass a prompt as an argument:

```bash
buddy enhance "make the readme better"
```

Or pipe a prompt through standard input:

```bash
printf 'make the readme better' | buddy enhance
```

Run the package without installing the command separately:

```bash
python -m buddy_cli enhance "make the readme better"
```

## Tests

```bash
python -m unittest discover -s tests -v
```

## Planned extension points

The enhancement logic is isolated in `buddy_cli.enhancer`, which allows future
enhancers—such as Ollama, an API provider, or an MCP tool—to be added without
changing the command-line interface.
