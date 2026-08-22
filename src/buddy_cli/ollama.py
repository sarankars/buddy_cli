"""Minimal Ollama HTTP client used by Buddy."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
from urllib import error, parse, request


class OllamaError(RuntimeError):
    """Base exception for Ollama communication failures."""


class OllamaConnectionError(OllamaError):
    """Raised when the local Ollama API cannot be reached."""


ModelProgress = Callable[[str, Optional[int], Optional[int]], None]


@dataclass(frozen=True)
class OllamaVersion:
    version: str


class OllamaClient:
    """Communicate with a localhost Ollama API without external HTTP packages."""

    def __init__(self, base_url: str, *, timeout: float = 120.0) -> None:
        parsed = parse.urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("Ollama endpoint must be a localhost HTTP URL")
        if parsed.path not in {"", "/"}:
            raise ValueError("Ollama endpoint must not contain a path")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _open(self, path: str, payload: Optional[Dict[str, object]] = None):
        data = None
        method = "GET"
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            method = "POST"
            headers["Content-Type"] = "application/json"

        http_request = request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            return request.urlopen(http_request, timeout=self.timeout)
        except (error.URLError, error.HTTPError, TimeoutError, OSError) as exc:
            raise OllamaConnectionError(
                f"could not reach Ollama at {self.base_url}: {exc}"
            ) from exc

    @staticmethod
    def _decode_json(raw: bytes) -> Dict[str, object]:
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OllamaError("Ollama returned an invalid JSON response") from exc
        if not isinstance(value, dict):
            raise OllamaError("Ollama returned an unexpected response")
        if value.get("error"):
            raise OllamaError(str(value["error"]))
        return value

    def get_version(self) -> OllamaVersion:
        with self._open("/api/version") as response:
            value = self._decode_json(response.read())
        version = value.get("version")
        if not isinstance(version, str) or not version:
            raise OllamaError("Ollama did not report its version")
        return OllamaVersion(version)

    def list_models(self) -> List[str]:
        with self._open("/api/tags") as response:
            value = self._decode_json(response.read())
        raw_models = value.get("models", [])
        if not isinstance(raw_models, list):
            raise OllamaError("Ollama returned an invalid model list")

        models: List[str] = []
        for entry in raw_models:
            if not isinstance(entry, dict):
                continue
            name = entry.get("model") or entry.get("name")
            if isinstance(name, str):
                models.append(name)
        return models

    def has_model(self, model: str) -> bool:
        return model in self.list_models()

    def pull_model(
        self,
        model: str,
        *,
        progress: Optional[ModelProgress] = None,
    ) -> None:
        with self._open("/api/pull", {"model": model, "stream": True}) as response:
            for raw_line in response:
                line = raw_line.strip()
                if not line:
                    continue
                value = self._decode_json(line)
                status = value.get("status", "working")
                completed = value.get("completed")
                total = value.get("total")
                if progress:
                    progress(
                        str(status),
                        completed if isinstance(completed, int) else None,
                        total if isinstance(total, int) else None,
                    )
                if status == "success":
                    return
        if not self.has_model(model):
            raise OllamaError(f"Ollama did not finish downloading {model}")

    def generate(self, model: str, prompt: str, *, system: str) -> str:
        payload: Dict[str, object] = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "keep_alive": "5m",
            "options": {
                "temperature": 0.1,
                "num_predict": 512,
            },
        }
        with self._open("/api/generate", payload) as response:
            value = self._decode_json(response.read())
        generated = value.get("response")
        if not isinstance(generated, str) or not generated.strip():
            raise OllamaError("Ollama returned an empty enhancement")
        return generated.strip()

    def wait_until_ready(
        self,
        *,
        timeout: float = 30.0,
        interval: float = 0.25,
    ) -> OllamaVersion:
        deadline = time.monotonic() + timeout
        last_error: Optional[Exception] = None
        while time.monotonic() < deadline:
            try:
                return self.get_version()
            except OllamaError as exc:
                last_error = exc
                time.sleep(interval)
        raise OllamaConnectionError(
            f"Ollama did not become ready within {timeout:.0f} seconds: {last_error}"
        )
