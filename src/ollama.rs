//! Minimal Ollama HTTP client used by Buddy.

use reqwest::blocking::Client;
use reqwest::header::{ACCEPT, CONTENT_TYPE};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::fmt;
use std::io::{BufRead, BufReader};
use std::thread;
use std::time::{Duration, Instant};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OllamaError {
    Connection(String),
    Api(String),
}

impl fmt::Display for OllamaError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Connection(msg) => write!(f, "{}", msg),
            Self::Api(msg) => write!(f, "{}", msg),
        }
    }
}

impl std::error::Error for OllamaError {}

pub type ModelProgress<'a> = Box<dyn FnMut(&str, Option<u64>, Option<u64>) + 'a>;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OllamaVersion {
    pub version: String,
}

#[derive(Clone)]
pub struct OllamaClient {
    pub base_url: String,
    pub timeout: Duration,
}

impl OllamaClient {
    pub fn new(base_url: &str) -> Result<Self, OllamaError> {
        Self::with_timeout(base_url, Duration::from_secs(120))
    }

    pub fn with_timeout(base_url: &str, timeout: Duration) -> Result<Self, OllamaError> {
        let trimmed = base_url.trim_end_matches('/');
        if !trimmed.starts_with("http://") {
            return Err(OllamaError::Connection(
                "Ollama endpoint must be a localhost HTTP URL".to_string(),
            ));
        }

        let host_part = trimmed.strip_prefix("http://").unwrap_or("");
        let host = host_part.split(':').next().unwrap_or("");
        if host != "127.0.0.1" && host != "localhost" && host != "[::1]" && host != "::1" {
            return Err(OllamaError::Connection(
                "Ollama endpoint must be a localhost HTTP URL".to_string(),
            ));
        }

        if host_part.contains('/') {
            return Err(OllamaError::Connection(
                "Ollama endpoint must not contain a path".to_string(),
            ));
        }

        Ok(Self {
            base_url: trimmed.to_string(),
            timeout,
        })
    }

    fn client(&self) -> Result<Client, OllamaError> {
        Client::builder()
            .timeout(self.timeout)
            .build()
            .map_err(|e| OllamaError::Connection(e.to_string()))
    }

    pub fn get_version(&self) -> Result<OllamaVersion, OllamaError> {
        let url = format!("{}/api/version", self.base_url);
        let client = self.client()?;
        let resp = client
            .get(&url)
            .header(ACCEPT, "application/json")
            .send()
            .map_err(|e| {
                OllamaError::Connection(format!(
                    "could not reach Ollama at {}: {}",
                    self.base_url, e
                ))
            })?;

        if !resp.status().is_success() {
            return Err(OllamaError::Api(format!("HTTP {}", resp.status())));
        }

        let val: Value = resp
            .json()
            .map_err(|e| OllamaError::Api(format!("invalid JSON: {}", e)))?;

        let version = val
            .get("version")
            .and_then(|v| v.as_str())
            .ok_or_else(|| OllamaError::Api("Ollama did not report its version".to_string()))?;

        Ok(OllamaVersion {
            version: version.to_string(),
        })
    }

    pub fn list_models(&self) -> Result<Vec<String>, OllamaError> {
        let url = format!("{}/api/tags", self.base_url);
        let client = self.client()?;
        let resp = client
            .get(&url)
            .header(ACCEPT, "application/json")
            .send()
            .map_err(|e| {
                OllamaError::Connection(format!(
                    "could not reach Ollama at {}: {}",
                    self.base_url, e
                ))
            })?;

        if !resp.status().is_success() {
            return Err(OllamaError::Api(format!("HTTP {}", resp.status())));
        }

        let val: Value = resp
            .json()
            .map_err(|e| OllamaError::Api(format!("invalid JSON: {}", e)))?;

        let models_arr = val
            .get("models")
            .and_then(|m| m.as_array())
            .ok_or_else(|| OllamaError::Api("Ollama returned an invalid model list".to_string()))?;

        let mut models = Vec::new();
        for item in models_arr {
            if let Some(name) = item
                .get("model")
                .or_else(|| item.get("name"))
                .and_then(|n| n.as_str())
            {
                models.push(name.to_string());
            }
        }

        Ok(models)
    }

    pub fn has_model(&self, model: &str) -> bool {
        self.list_models()
            .map(|models| models.iter().any(|m| m == model))
            .unwrap_or(false)
    }

    pub fn pull_model(
        &self,
        model: &str,
        mut progress: Option<ModelProgress>,
    ) -> Result<(), OllamaError> {
        let url = format!("{}/api/pull", self.base_url);
        let client = self.client()?;

        let body = serde_json::json!({
            "model": model,
            "stream": true,
        });

        let resp = client
            .post(&url)
            .header(ACCEPT, "application/json")
            .header(CONTENT_TYPE, "application/json")
            .json(&body)
            .send()
            .map_err(|e| {
                OllamaError::Connection(format!(
                    "could not reach Ollama at {}: {}",
                    self.base_url, e
                ))
            })?;

        let reader = BufReader::new(resp);
        for line in reader.lines() {
            let line_str =
                line.map_err(|e| OllamaError::Api(format!("stream read error: {}", e)))?;
            let trimmed = line_str.trim();
            if trimmed.is_empty() {
                continue;
            }

            let val: Value = serde_json::from_str(trimmed)
                .map_err(|e| OllamaError::Api(format!("invalid stream JSON: {}", e)))?;

            if let Some(err) = val.get("error").and_then(|e| e.as_str()) {
                return Err(OllamaError::Api(err.to_string()));
            }

            let status = val
                .get("status")
                .and_then(|s| s.as_str())
                .unwrap_or("working");
            let completed = val.get("completed").and_then(|c| c.as_u64());
            let total = val.get("total").and_then(|t| t.as_u64());

            if let Some(ref mut p) = progress {
                p(status, completed, total);
            }

            if status == "success" {
                return Ok(());
            }
        }

        if !self.has_model(model) {
            return Err(OllamaError::Api(format!(
                "Ollama did not finish downloading {}",
                model
            )));
        }

        Ok(())
    }

    pub fn generate(
        &self,
        model: &str,
        prompt: &str,
        system: &str,
        response_format: Option<Value>,
        options: Option<HashMap<String, Value>>,
    ) -> Result<String, OllamaError> {
        let url = format!("{}/api/generate", self.base_url);
        let client = self.client()?;

        let mut generation_options = serde_json::Map::new();
        generation_options.insert("temperature".to_string(), serde_json::json!(0.1));
        generation_options.insert("num_predict".to_string(), serde_json::json!(512));

        if let Some(opts) = options {
            for (k, v) in opts {
                generation_options.insert(k, v);
            }
        }

        let mut payload = serde_json::Map::new();
        payload.insert("model".to_string(), serde_json::json!(model));
        payload.insert("prompt".to_string(), serde_json::json!(prompt));
        payload.insert("system".to_string(), serde_json::json!(system));
        payload.insert("stream".to_string(), serde_json::json!(false));
        payload.insert("keep_alive".to_string(), serde_json::json!("5m"));
        payload.insert("options".to_string(), Value::Object(generation_options));

        if let Some(fmt) = response_format {
            payload.insert("format".to_string(), fmt);
        }

        let resp = client
            .post(&url)
            .header(ACCEPT, "application/json")
            .header(CONTENT_TYPE, "application/json")
            .json(&Value::Object(payload))
            .send()
            .map_err(|e| {
                OllamaError::Connection(format!(
                    "could not reach Ollama at {}: {}",
                    self.base_url, e
                ))
            })?;

        let val: Value = resp
            .json()
            .map_err(|e| OllamaError::Api(format!("invalid JSON: {}", e)))?;

        if let Some(err) = val.get("error").and_then(|e| e.as_str()) {
            return Err(OllamaError::Api(err.to_string()));
        }

        let generated = val
            .get("response")
            .and_then(|r| r.as_str())
            .ok_or_else(|| OllamaError::Api("Ollama returned an empty enhancement".to_string()))?;

        let trimmed = generated.trim();
        if trimmed.is_empty() {
            return Err(OllamaError::Api(
                "Ollama returned an empty enhancement".to_string(),
            ));
        }

        Ok(trimmed.to_string())
    }

    pub fn wait_until_ready(
        &self,
        timeout: Duration,
        interval: Duration,
    ) -> Result<OllamaVersion, OllamaError> {
        let deadline = Instant::now() + timeout;
        let mut last_error = None;

        while Instant::now() < deadline {
            match self.get_version() {
                Ok(v) => return Ok(v),
                Err(e) => {
                    last_error = Some(e);
                    thread::sleep(interval);
                }
            }
        }

        Err(OllamaError::Connection(format!(
            "Ollama did not become ready within {:.0} seconds: {:?}",
            timeout.as_secs_f64(),
            last_error
        )))
    }
}
