"""End-to-end setup orchestration."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Callable, List, Optional

from buddy_cli.config import BuddyConfig, ConfigError, ConfigStore
from buddy_cli.constants import DEFAULT_MODEL, MODEL_DOWNLOAD_ESTIMATE_BYTES
from buddy_cli.download import DownloadProgress
from buddy_cli.ollama import ModelProgress, OllamaClient, OllamaError
from buddy_cli.paths import AppPaths
from buddy_cli.runtime_manager import RuntimeManager
from buddy_cli.runtime_manifest import format_bytes, resolve_runtime_spec


class ProvisioningError(RuntimeError):
    """Raised when Buddy setup cannot complete."""


class SetupCancelled(ProvisioningError):
    """Raised when the user declines a required setup action."""


Confirm = Callable[[str, bool], bool]
Emit = Callable[[str], None]


@dataclass(frozen=True)
class SetupResult:
    config: BuddyConfig
    installed_runtime: bool
    installed_model: bool


class Provisioner:
    """Provision an Ollama runtime and prompt-enhancement model."""

    SMOKE_TEST_SYSTEM = (
        "Rewrite rough prompts. Return only the improved prompt and never answer it."
    )
    FREE_SPACE_BUFFER_BYTES = 500_000_000

    def __init__(
        self,
        paths: AppPaths,
        config_store: ConfigStore,
        runtime_manager: RuntimeManager,
    ) -> None:
        self.paths = paths
        self.config_store = config_store
        self.runtime_manager = runtime_manager

    def plan(self, model: str = DEFAULT_MODEL) -> List[str]:
        """Return a side-effect-free summary of what setup would do."""
        messages: List[str] = []
        try:
            config = self.config_store.load()
        except ConfigError as exc:
            messages.append(f"Existing configuration is invalid: {exc}")
            config = None

        selection = self.runtime_manager.discover(config)
        if selection is None:
            spec = resolve_runtime_spec()
            messages.append(
                "Download Buddy-managed Ollama "
                f"{spec.version} ({format_bytes(spec.size)})"
            )
            messages.append(f"Install the runtime under {self.paths.runtimes_dir}")
            messages.append(
                "Download model "
                f"{model} (approximately {format_bytes(MODEL_DOWNLOAD_ESTIMATE_BYTES)})"
            )
        else:
            messages.append(f"Use {selection.provider} Ollama at {selection.base_url}")
            if self.runtime_manager.api_is_ready(selection.base_url):
                try:
                    if OllamaClient(selection.base_url).has_model(model):
                        messages.append(f"Reuse installed model {model}")
                    else:
                        messages.append(f"Download missing model {model}")
                except OllamaError:
                    messages.append(f"Verify or download model {model}")
            else:
                messages.append("Start Ollama and verify its local API")
                messages.append(f"Verify or download model {model}")
        messages.append("Run an enhancement smoke test and save configuration")
        return messages

    def setup(
        self,
        *,
        model: str = DEFAULT_MODEL,
        confirm: Confirm,
        emit: Emit,
        download_progress: Optional[DownloadProgress] = None,
        model_progress: Optional[ModelProgress] = None,
    ) -> SetupResult:
        self.paths.ensure_directories()
        try:
            existing_config = self.config_store.load()
        except ConfigError as exc:
            emit(f"Ignoring invalid configuration: {exc}")
            existing_config = None

        selection = self.runtime_manager.discover(existing_config)
        installed_runtime = False
        if selection is None:
            spec = resolve_runtime_spec()
            runtime_working_space = spec.size * 2
            if spec.operating_system == "windows":
                runtime_working_space = max(runtime_working_space, 4_000_000_000)
            required_space = (
                runtime_working_space
                + MODEL_DOWNLOAD_ESTIMATE_BYTES
                + self.FREE_SPACE_BUFFER_BYTES
            )
            available_space = shutil.disk_usage(self.paths.root).free
            if available_space < required_space:
                raise ProvisioningError(
                    "not enough free space for Ollama and the enhancement model: "
                    f"need approximately {format_bytes(required_space)}, "
                    f"have {format_bytes(available_space)}"
                )
            emit(f"Storage check passed ({format_bytes(available_space)} available)")
            message = (
                f"Download Ollama {spec.version} ({format_bytes(spec.size)}) "
                f"into {self.paths.runtimes_dir}?"
            )
            if not confirm(message, False):
                raise SetupCancelled("Ollama runtime download was declined")
            selection = self.runtime_manager.install_managed(
                download_progress=download_progress,
                status_callback=emit,
            )
            installed_runtime = True
            emit("Ollama runtime is installed and verified")
        else:
            emit(f"Using {selection.provider} Ollama at {selection.base_url}")

        try:
            self.runtime_manager.start(selection)
        except Exception as exc:
            raise ProvisioningError(f"could not start Ollama: {exc}") from exc

        client = OllamaClient(selection.base_url)
        try:
            version = client.get_version()
            emit(f"Ollama {version.version} is running")
            has_model = client.has_model(model)
        except OllamaError as exc:
            raise ProvisioningError(str(exc)) from exc

        installed_model = False
        if not has_model:
            message = (
                f"Download model {model} "
                f"(approximately {format_bytes(MODEL_DOWNLOAD_ESTIMATE_BYTES)})?"
            )
            if not confirm(message, False):
                raise SetupCancelled("model download was declined")
            emit(f"Downloading model {model}")
            try:
                client.pull_model(model, progress=model_progress)
            except OllamaError as exc:
                raise ProvisioningError(f"could not download {model}: {exc}") from exc
            installed_model = True
            emit(f"Model {model} is installed")
        else:
            emit(f"Model {model} is already installed")

        try:
            client.generate(
                model,
                "say hello more clearly",
                system=self.SMOKE_TEST_SYSTEM,
            )
        except OllamaError as exc:
            raise ProvisioningError(f"enhancement smoke test failed: {exc}") from exc

        config = BuddyConfig(
            provider=selection.provider,
            base_url=selection.base_url,
            model=model,
            executable=str(selection.executable) if selection.executable else None,
            runtime_version=selection.runtime_version,
        )
        self.config_store.save(config)
        emit("Enhancement smoke test passed")
        return SetupResult(config, installed_runtime, installed_model)
