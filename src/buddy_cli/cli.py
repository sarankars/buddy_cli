"""Command-line interface for Buddy."""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence, TextIO

from buddy_cli import __version__
from buddy_cli.enhancer import EmptyPromptError, RuleBasedEnhancer


def build_parser() -> argparse.ArgumentParser:
    """Build and return the Buddy argument parser."""
    parser = argparse.ArgumentParser(
        prog="buddy",
        description="Enhance rough prompts before sending them to an AI assistant.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    enhance_parser = subparsers.add_parser(
        "enhance",
        help="Improve a prompt using the configured enhancer.",
    )
    enhance_parser.add_argument(
        "prompt",
        nargs="*",
        help="Prompt to enhance. When omitted, Buddy reads from standard input.",
    )
    return parser


def _read_prompt(parts: Sequence[str], input_stream: TextIO) -> str:
    if parts:
        return " ".join(parts)

    if input_stream.isatty():
        raise EmptyPromptError(
            "provide a prompt as an argument or pipe one through standard input"
        )
    return input_stream.read()


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    input_stream: Optional[TextIO] = None,
    output_stream: Optional[TextIO] = None,
    error_stream: Optional[TextIO] = None,
) -> int:
    """Run the Buddy CLI and return its process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    stdin = input_stream or sys.stdin
    stdout = output_stream or sys.stdout
    stderr = error_stream or sys.stderr

    if args.command == "enhance":
        try:
            prompt = _read_prompt(args.prompt, stdin)
            enhanced = RuleBasedEnhancer().enhance(prompt)
        except EmptyPromptError as exc:
            print(f"buddy: error: {exc}", file=stderr)
            return 2

        print(enhanced, file=stdout)
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
