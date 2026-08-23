//! Persistent Buddy configuration.

use serde::{Deserialize, Serialize};
use std::fmt;
use std::fs;
use std::io::Write;
use tempfile::NamedTempFile;

use crate::constants::CONFIG_SCHEMA_VERSION;
use crate::paths::AppPaths;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ConfigError {
    MissingOrInvalidField(&'static str),
    UnsupportedSchemaVersion(u32),
    UnsupportedProvider(String),
    IoOrParseError(String),
    NotAnObject,
}

impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingOrInvalidField(field) => {
                write!(f, "configuration field '{}' must be a string", field)
            }
            Self::UnsupportedSchemaVersion(ver) => {
                write!(f, "unsupported configuration schema version: {}", ver)
            }
            Self::UnsupportedProvider(p) => {
                write!(f, "unsupported Ollama provider: {}", p)
            }
            Self::IoOrParseError(err) => {
                write!(f, "could not read Buddy configuration: {}", err)
            }
            Self::NotAnObject => {
                write!(f, "Buddy configuration must contain a JSON object")
            }
        }
    }
}

impl std::error::Error for ConfigError {}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BuddyConfig {
    pub provider: String,
    pub base_url: String,
    pub model: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub executable: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub runtime_version: Option<String>,
    #[serde(default = "default_schema_version")]
    pub schema_version: u32,
}

fn default_schema_version() -> u32 {
    CONFIG_SCHEMA_VERSION
}

impl BuddyConfig {
    pub fn new(
        provider: impl Into<String>,
        base_url: impl Into<String>,
        model: impl Into<String>,
        executable: Option<String>,
        runtime_version: Option<String>,
    ) -> Result<Self, ConfigError> {
        let provider_str = provider.into();
        let base_url_str = base_url.into();
        let model_str = model.into();

        if provider_str.trim().is_empty() {
            return Err(ConfigError::MissingOrInvalidField("provider"));
        }
        if provider_str != "managed" && provider_str != "system" {
            return Err(ConfigError::UnsupportedProvider(provider_str));
        }
        if base_url_str.trim().is_empty() {
            return Err(ConfigError::MissingOrInvalidField("base_url"));
        }
        if model_str.trim().is_empty() {
            return Err(ConfigError::MissingOrInvalidField("model"));
        }

        Ok(Self {
            provider: provider_str,
            base_url: base_url_str,
            model: model_str,
            executable,
            runtime_version,
            schema_version: CONFIG_SCHEMA_VERSION,
        })
    }

    pub fn from_value(value: serde_json::Value) -> Result<Self, ConfigError> {
        let obj = value.as_object().ok_or(ConfigError::NotAnObject)?;

        let get_str = |key: &'static str| -> Result<String, ConfigError> {
            let val = obj
                .get(key)
                .ok_or(ConfigError::MissingOrInvalidField(key))?;
            let s = val
                .as_str()
                .ok_or(ConfigError::MissingOrInvalidField(key))?;
            if s.trim().is_empty() {
                return Err(ConfigError::MissingOrInvalidField(key));
            }
            Ok(s.to_string())
        };

        let provider = get_str("provider")?;
        if provider != "managed" && provider != "system" {
            return Err(ConfigError::UnsupportedProvider(provider));
        }

        let base_url = get_str("base_url")?;
        let model = get_str("model")?;

        let schema_version = if let Some(v) = obj.get("schema_version") {
            v.as_u64()
                .map(|n| n as u32)
                .ok_or(ConfigError::UnsupportedSchemaVersion(0))?
        } else {
            CONFIG_SCHEMA_VERSION
        };

        if schema_version != CONFIG_SCHEMA_VERSION {
            return Err(ConfigError::UnsupportedSchemaVersion(schema_version));
        }

        let executable = if let Some(v) = obj.get("executable") {
            if v.is_null() {
                None
            } else {
                Some(
                    v.as_str()
                        .ok_or(ConfigError::MissingOrInvalidField("executable"))?
                        .to_string(),
                )
            }
        } else {
            None
        };

        let runtime_version = if let Some(v) = obj.get("runtime_version") {
            if v.is_null() {
                None
            } else {
                Some(
                    v.as_str()
                        .ok_or(ConfigError::MissingOrInvalidField("runtime_version"))?
                        .to_string(),
                )
            }
        } else {
            None
        };

        Ok(Self {
            provider,
            base_url,
            model,
            executable,
            runtime_version,
            schema_version,
        })
    }
}

pub struct ConfigStore {
    pub paths: AppPaths,
}

impl ConfigStore {
    pub fn new(paths: AppPaths) -> Self {
        Self { paths }
    }

    pub fn load(&self) -> Result<Option<BuddyConfig>, ConfigError> {
        let config_file = self.paths.config_file();
        if !config_file.exists() {
            return Ok(None);
        }

        let content = fs::read_to_string(&config_file)
            .map_err(|e| ConfigError::IoOrParseError(e.to_string()))?;

        let value: serde_json::Value = serde_json::from_str(&content)
            .map_err(|e| ConfigError::IoOrParseError(e.to_string()))?;

        BuddyConfig::from_value(value).map(Some)
    }

    pub fn save(&self, config: &BuddyConfig) -> Result<(), Box<dyn std::error::Error>> {
        self.paths.ensure_directories()?;

        let mut temp_file = NamedTempFile::new_in(&self.paths.root)?;
        let json_data = serde_json::to_string_pretty(config)?;
        temp_file.write_all(json_data.as_bytes())?;
        temp_file.write_all(b"\n")?;
        temp_file.flush()?;
        temp_file.as_file().sync_all()?;

        temp_file.persist(self.paths.config_file())?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_config_serialization_roundtrip() {
        let dir = tempdir().unwrap();
        let paths = AppPaths::new(dir.path());
        let store = ConfigStore::new(paths);

        assert_eq!(store.load().unwrap(), None);

        let config = BuddyConfig::new(
            "managed",
            "http://127.0.0.1:11435",
            "qwen2.5:3b-instruct",
            Some("/path/to/ollama".to_string()),
            Some("0.32.5".to_string()),
        )
        .unwrap();

        store.save(&config).unwrap();
        let loaded = store.load().unwrap().expect("should load config");
        assert_eq!(loaded, config);
    }

    #[test]
    fn test_invalid_config() {
        let dir = tempdir().unwrap();
        let paths = AppPaths::new(dir.path());
        let store = ConfigStore::new(paths.clone());

        fs::create_dir_all(&paths.root).unwrap();
        fs::write(paths.config_file(), "invalid json").unwrap();
        assert!(store.load().is_err());

        fs::write(
            paths.config_file(),
            r#"{"provider": "unknown", "base_url": "x", "model": "y"}"#,
        )
        .unwrap();
        assert!(store.load().is_err());
    }
}
