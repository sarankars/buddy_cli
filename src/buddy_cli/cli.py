"""Command-line interface for Buddy."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Optional, Sequence, TextIO

from buddy_cli import __version__
from buddy_cli.config import ConfigError
from buddy_cli.constants import DEFAULT_MODEL
from buddy_cli.enhancer import EmptyPromptError, OllamaEnhancer, RuleBasedEnhancer
from buddy_cli.ollama import OllamaClient, OllamaError
from buddy_cli.provisioning import ProvisioningError, SetupCancelled
from buddy_cli.runtime_manifest import format_bytes
from buddy_cli.services import Services, build_services


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

    setup_parser = subparsers.add_parser(
        "setup",
        help="Provision and verify the local enhancement runtime.",
    )
    setup_parser.add_argument(
        "--yes",
        action="store_true",
        help="Accept required runtime and model downloads.",
    )
    setup_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the setup plan without changing anything.",
    )
    setup_parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model to provision (default: {DEFAULT_MODEL}).",
    )

    enhance_parser = subparsers.add_parser(
        "enhance",
        help="Improve a rough prompt.",
    )
    enhance_parser.add_argument(
        "prompt",
        nargs="*",
        help="Prompt to enhance. When omitted, Buddy reads from standard input.",
    )
    enhance_parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the deterministic enhancer without Ollama.",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Diagnose Buddy, Ollama, and the enhancement model.",
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Return the diagnostic report as JSON.",
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


def _format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, remaining_seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {remaining_seconds:02d}s"
    hours, remaining_minutes = divmod(minutes, 60)
    return f"{hours}h {remaining_minutes:02d}m"


@dataclass
class TerminalUI:
    input_stream: TextIO
    output_stream: TextIO
    assume_yes: bool = False
    _last_download_percent: int = -1
    _last_model_percent: int = -1
    _download_started_at: Optional[float] = None
    _download_started_bytes: int = 0
    _last_download_report_at: float = 0.0

    def emit(self, message: str) -> None:
        print(f"[buddy] {message}", file=self.output_stream)

    def confirm(self, message: str, default: bool = False) -> bool:
        if self.assume_yes:
            self.emit(f"{message} yes")
            return True
        if not self.input_stream.isatty():
            raise SetupCancelled(
                f"confirmation required: {message} Run 'buddy setup --yes' "
                "for non-interactive setup."
            )

        suffix = "[Y/n]" if default else "[y/N]"
        print(f"{message} {suffix} ", end="", file=self.output_stream, flush=True)
        response = self.input_stream.readline().strip().lower()
        if not response:
            return default
        return response in {"y", "yes"}

    def download_progress(self, completed: int, total: Optional[int]) -> None:
        now = time.monotonic()
        if self._download_started_at is None:
            self._download_started_at = now
            self._download_started_bytes = completed

        if total:
            percent = min(100, int(completed * 100 / total))
            report_is_due = now - self._last_download_report_at >= 1.0
            if (
                percent == self._last_download_percent
                and completed != total
                and not report_is_due
            ):
                return
            self._last_download_percent = percent
            self._last_download_report_at = now
            message = (
                f"Runtime download {percent}% "
                f"({format_bytes(completed)} of {format_bytes(total)})"
            )
            elapsed = now - self._download_started_at
            transferred = completed - self._download_started_bytes
            if elapsed > 0 and transferred > 0:
                bytes_per_second = transferred / elapsed
                remaining = max(0, total - completed)
                eta_seconds = int(remaining / bytes_per_second)
                message += (
                    f" at {format_bytes(int(bytes_per_second))}/s, "
                    f"ETA {_format_duration(eta_seconds)}"
                )
            self.emit(message)
        elif completed:
            if now - self._last_download_report_at >= 1.0:
                self._last_download_report_at = now
                self.emit(f"Runtime download {format_bytes(completed)}")

    def model_progress(
        self,
        status: str,
        completed: Optional[int],
        total: Optional[int],
    ) -> None:
        if completed is not None and total:
            percent = min(100, int(completed * 100 / total))
            if percent == self._last_model_percent:
                return
            self._last_model_percent = percent
            self.emit(
                f"Model download {percent}% "
                f"({format_bytes(completed)} of {format_bytes(total)})"
            )
        elif status in {"pulling manifest", "verifying sha256 digest", "success"}:
            self.emit(f"Model: {status}")


def _run_setup(
    args: argparse.Namespace,
    services: Services,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    ui = TerminalUI(stdin, stdout, assume_yes=args.yes)
    if args.dry_run:
        print("Buddy setup plan:", file=stdout)
        try:
            for index, message in enumerate(services.provisioner.plan(args.model), 1):
                print(f"  {index}. {message}", file=stdout)
        except Exception as exc:
            print(f"buddy: setup plan failed: {exc}", file=stderr)
            return 1
        return 0

    try:
        services.provisioner.setup(
            model=args.model,
            confirm=ui.confirm,
            emit=ui.emit,
            download_progress=ui.download_progress,
            model_progress=ui.model_progress,
        )
    except SetupCancelled as exc:
        print(f"buddy: setup cancelled: {exc}", file=stderr)
        return 2
    except ProvisioningError as exc:
        print(f"buddy: setup failed: {exc}", file=stderr)
        print("Run 'buddy doctor' for diagnostics.", file=stderr)
        return 1

    ui.emit("Buddy is ready")
    return 0


def _offer_first_run_setup(
    services: Services,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> bool:
    ui = TerminalUI(stdin, stdout)
    try:
        if not ui.confirm("Buddy is not configured. Run automatic setup now?", True):
            return False
        services.provisioner.setup(
            confirm=ui.confirm,
            emit=ui.emit,
            download_progress=ui.download_progress,
            model_progress=ui.model_progress,
        )
        ui.emit("Buddy is ready")
        return True
    except (ProvisioningError, SetupCancelled) as exc:
        print(f"buddy: automatic setup did not complete: {exc}", file=stderr)
        return False


def _run_enhance(
    args: argparse.Namespace,
    services: Services,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    try:
        prompt = _read_prompt(args.prompt, stdin)
    except EmptyPromptError as exc:
        print(f"buddy: error: {exc}", file=stderr)
        return 2

    if args.offline:
        print(RuleBasedEnhancer().enhance(prompt), file=stdout)
        return 0

    try:
        config = services.config_store.load()
    except ConfigError as exc:
        print(f"buddy: invalid configuration: {exc}", file=stderr)
        config = None

    if config is None and _offer_first_run_setup(services, stdin, stdout, stderr):
        try:
            config = services.config_store.load()
        except ConfigError:
            config = None

    if config is not None:
        try:
            selection = services.runtime_manager.selection_from_config(config)
            services.runtime_manager.start(selection)
            enhanced = OllamaEnhancer(
                OllamaClient(config.base_url),
                config.model,
            ).enhance(prompt)
            print(enhanced, file=stdout)
            return 0
        except (OllamaError, OSError, ValueError, RuntimeError) as exc:
            print(
                f"buddy: local AI unavailable ({exc}); using offline enhancer",
                file=stderr,
            )

    if config is None:
        print(
            "buddy: local AI is not configured; using offline enhancer. "
            "Run 'buddy setup' to enable AI enhancement.",
            file=stderr,
        )
    print(RuleBasedEnhancer().enhance(prompt), file=stdout)
    return 0


def _run_doctor(
    args: argparse.Namespace,
    services: Services,
    stdout: TextIO,
) -> int:
    report = services.doctor.run()
    if args.json:
        json.dump(report.to_dict(), stdout, indent=2)
        stdout.write("\n")
    else:
        for check in report.checks:
            print(f"[{check.status}] {check.name}: {check.detail}", file=stdout)
        print(
            "Buddy is ready." if report.healthy else "Buddy needs attention.",
            file=stdout,
        )
    return 0 if report.healthy else 1


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    input_stream: Optional[TextIO] = None,
    output_stream: Optional[TextIO] = None,
    error_stream: Optional[TextIO] = None,
    services: Optional[Services] = None,
) -> int:
    """Run the Buddy CLI and return its process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    stdin = input_stream or sys.stdin
    stdout = output_stream or sys.stdout
    stderr = error_stream or sys.stderr
    app_services = services or build_services()

    if args.command == "setup":
        return _run_setup(args, app_services, stdin, stdout, stderr)
    if args.command == "enhance":
        return _run_enhance(args, app_services, stdin, stdout, stderr)
    if args.command == "doctor":
        return _run_doctor(args, app_services, stdout)

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
