//! Shared Buddy constants.

pub const APP_NAME: &str = "Buddy";
pub const CONFIG_SCHEMA_VERSION: u32 = 1;
pub const DEFAULT_MODEL: &str = "qwen2.5:3b-instruct";
pub const DEFAULT_OLLAMA_BASE_URL: &str = "http://127.0.0.1:11434";
pub const MANAGED_OLLAMA_BASE_URL: &str = "http://127.0.0.1:11435";
pub const OLLAMA_RUNTIME_VERSION: &str = "0.32.5";

/// The registry reports exact transfer totals while pulling. This estimate is
/// used only in the consent message before the local API is available.
pub const MODEL_DOWNLOAD_ESTIMATE_BYTES: u64 = 1_900_000_000;
