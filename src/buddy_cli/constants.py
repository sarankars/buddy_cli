"""Shared Buddy constants."""

APP_NAME = "Buddy"
CONFIG_SCHEMA_VERSION = 1
DEFAULT_MODEL = "qwen2.5:3b-instruct"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
MANAGED_OLLAMA_BASE_URL = "http://127.0.0.1:11435"
OLLAMA_RUNTIME_VERSION = "0.32.5"

# The registry reports exact transfer totals while pulling. This estimate is
# used only in the consent message before the local API is available.
MODEL_DOWNLOAD_ESTIMATE_BYTES = 1_900_000_000
