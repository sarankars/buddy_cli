"""Tests for the local Ollama HTTP client."""

import io
import unittest
from unittest.mock import patch

from buddy_cli.ollama import OllamaClient


class FakeResponse:
    def __init__(self, content: bytes = b"", lines=None) -> None:
        self.content = io.BytesIO(content)
        self.lines = list(lines or [])

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.content.close()

    def read(self) -> bytes:
        return self.content.read()

    def __iter__(self):
        return iter(self.lines)


class OllamaClientTests(unittest.TestCase):
    def test_rejects_non_local_endpoint(self) -> None:
        with self.assertRaises(ValueError):
            OllamaClient("https://example.com")

    def test_reads_version_and_models(self) -> None:
        client = OllamaClient("http://127.0.0.1:11434")
        responses = [
            FakeResponse(b'{"version":"0.32.5"}'),
            FakeResponse(b'{"models":[{"model":"qwen2.5:3b-instruct"}]}'),
        ]

        with patch.object(client, "_open", side_effect=responses):
            self.assertEqual(client.get_version().version, "0.32.5")
            self.assertTrue(client.has_model("qwen2.5:3b-instruct"))

    def test_pulls_model_and_reports_progress(self) -> None:
        client = OllamaClient("http://127.0.0.1:11434")
        response = FakeResponse(
            lines=[
                b'{"status":"pulling","completed":5,"total":10}\n',
                b'{"status":"success"}\n',
            ]
        )
        progress = []

        with patch.object(client, "_open", return_value=response):
            client.pull_model(
                "test-model",
                progress=lambda status, completed, total: progress.append(
                    (status, completed, total)
                ),
            )

        self.assertEqual(progress[0], ("pulling", 5, 10))
        self.assertEqual(progress[-1], ("success", None, None))

    def test_generates_an_enhanced_prompt(self) -> None:
        client = OllamaClient("http://127.0.0.1:11434")
        schema = {"type": "object"}
        with patch.object(
            client,
            "_open",
            return_value=FakeResponse(b'{"response":"Clear prompt"}'),
        ) as open_request:
            result = client.generate(
                "model",
                "rough",
                system="rewrite",
                response_format=schema,
                options={"temperature": 0, "seed": 42},
            )

        self.assertEqual(result, "Clear prompt")
        payload = open_request.call_args.args[1]
        self.assertEqual(payload["format"], schema)
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertEqual(payload["options"]["seed"], 42)
        self.assertEqual(payload["options"]["num_predict"], 512)
