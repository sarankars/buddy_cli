//! Buddy installation diagnostics.

use serde::{Deserialize, Serialize};
use std::fs::{self, OpenOptions};
use std::path::PathBuf;
use std::time::Duration;

use crate::config::{BuddyConfig, ConfigStore};
use crate::constants::{DEFAULT_MODEL, DEFAULT_OLLAMA_BASE_URL};
use crate::ollama::OllamaClient;
use crate::paths::AppPaths;
use crate::runtime_manager::RuntimeManager;
use crate::runtime_manifest::resolve_runtime_spec;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DiagnosticCheck {
    pub status: String,
    pub name: String,
    pub detail: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DiagnosticReport {
    pub healthy: bool,
    pub checks: Vec<DiagnosticCheck>,
}

impl DiagnosticReport {
    pub fn new(checks: Vec<DiagnosticCheck>) -> Self {
        let healthy = !checks.iter().any(|c| c.status == "FAIL");
        Self { healthy, checks }
    }
}

pub struct Doctor {
    pub paths: AppPaths,
    pub config_store: ConfigStore,
    pub runtime_manager: RuntimeManager,
}

impl Doctor {
    pub fn new(
        paths: AppPaths,
        config_store: ConfigStore,
        runtime_manager: RuntimeManager,
    ) -> Self {
        Self {
            paths,
            config_store,
            runtime_manager,
        }
    }

    fn check_storage_writable(&self) -> bool {
        let mut target = self.paths.root.clone();
        while !target.exists() {
            if let Some(parent) = target.parent() {
                if parent == target {
                    break;
                }
                target = parent.to_path_buf();
            } else {
                break;
            }
        }

        let probe = target.join(".buddy-probe-write-test");
        if let Ok(mut file) = OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(&probe)
        {
            use std::io::Write;
            let _ = file.write_all(b"probe");
            drop(file);
            let _ = fs::remove_file(&probe);
            true
        } else {
            false
        }
    }

    pub fn run(&self) -> DiagnosticReport {
        let mut checks = Vec::new();

        // 1. Platform check
        match resolve_runtime_spec() {
            Ok(spec) => {
                checks.push(DiagnosticCheck {
                    status: "PASS".to_string(),
                    name: "platform".to_string(),
                    detail: format!(
                        "managed runtime available for {}/{}",
                        spec.operating_system, spec.architecture
                    ),
                });
            }
            Err(e) => {
                checks.push(DiagnosticCheck {
                    status: "FAIL".to_string(),
                    name: "platform".to_string(),
                    detail: e.to_string(),
                });
            }
        }

        // 2. Storage check
        if self.check_storage_writable() {
            checks.push(DiagnosticCheck {
                status: "PASS".to_string(),
                name: "storage".to_string(),
                detail: format!("Buddy can write under {}", self.paths.root.display()),
            });
        } else {
            checks.push(DiagnosticCheck {
                status: "FAIL".to_string(),
                name: "storage".to_string(),
                detail: format!("Buddy cannot write under {}", self.paths.root.display()),
            });
        }

        // 3. Configuration check
        let config: Option<BuddyConfig> = match self.config_store.load() {
            Ok(Some(cfg)) => {
                checks.push(DiagnosticCheck {
                    status: "PASS".to_string(),
                    name: "configuration".to_string(),
                    detail: format!("configured for {} Ollama", cfg.provider),
                });
                Some(cfg)
            }
            Ok(None) => {
                checks.push(DiagnosticCheck {
                    status: "FAIL".to_string(),
                    name: "configuration".to_string(),
                    detail: "Buddy has not been set up; run 'buddy setup'".to_string(),
                });
                None
            }
            Err(e) => {
                checks.push(DiagnosticCheck {
                    status: "FAIL".to_string(),
                    name: "configuration".to_string(),
                    detail: e.to_string(),
                });
                None
            }
        };

        // 4. Runtime check
        if let Some(ref cfg) = config {
            if cfg.provider == "managed" {
                let exe = cfg.executable.as_ref().map(PathBuf::from);
                if let Some(ref path) = exe {
                    if path.is_file() {
                        checks.push(DiagnosticCheck {
                            status: "PASS".to_string(),
                            name: "runtime".to_string(),
                            detail: path.display().to_string(),
                        });
                    } else {
                        checks.push(DiagnosticCheck {
                            status: "FAIL".to_string(),
                            name: "runtime".to_string(),
                            detail: "managed Ollama executable is missing".to_string(),
                        });
                    }
                } else {
                    checks.push(DiagnosticCheck {
                        status: "FAIL".to_string(),
                        name: "runtime".to_string(),
                        detail: "managed Ollama executable is missing".to_string(),
                    });
                }
            } else {
                let exe = RuntimeManager::find_system_executable();
                if let Some(path) = exe {
                    checks.push(DiagnosticCheck {
                        status: "PASS".to_string(),
                        name: "runtime".to_string(),
                        detail: path.display().to_string(),
                    });
                } else {
                    checks.push(DiagnosticCheck {
                        status: "WARN".to_string(),
                        name: "runtime".to_string(),
                        detail: "system Ollama executable not found".to_string(),
                    });
                }
            }
        } else {
            let exe = RuntimeManager::find_system_executable();
            if let Some(path) = exe {
                checks.push(DiagnosticCheck {
                    status: "PASS".to_string(),
                    name: "runtime".to_string(),
                    detail: path.display().to_string(),
                });
            } else {
                checks.push(DiagnosticCheck {
                    status: "WARN".to_string(),
                    name: "runtime".to_string(),
                    detail: "system Ollama executable not found".to_string(),
                });
            }
        }

        // 5. API & Model checks
        let base_url = config
            .as_ref()
            .map(|c| c.base_url.as_str())
            .unwrap_or(DEFAULT_OLLAMA_BASE_URL);
        let model = config
            .as_ref()
            .map(|c| c.model.as_str())
            .unwrap_or(DEFAULT_MODEL);

        match OllamaClient::with_timeout(base_url, Duration::from_secs(2)) {
            Ok(client) => match client.get_version() {
                Ok(version) => {
                    checks.push(DiagnosticCheck {
                        status: "PASS".to_string(),
                        name: "api".to_string(),
                        detail: format!("Ollama {} at {}", version.version, base_url),
                    });
                    if client.has_model(model) {
                        checks.push(DiagnosticCheck {
                            status: "PASS".to_string(),
                            name: "model".to_string(),
                            detail: model.to_string(),
                        });
                    } else {
                        checks.push(DiagnosticCheck {
                            status: "FAIL".to_string(),
                            name: "model".to_string(),
                            detail: format!("{} is not installed; run 'buddy setup'", model),
                        });
                    }
                }
                Err(e) => {
                    checks.push(DiagnosticCheck {
                        status: "FAIL".to_string(),
                        name: "api".to_string(),
                        detail: e.to_string(),
                    });
                    checks.push(DiagnosticCheck {
                        status: "WARN".to_string(),
                        name: "model".to_string(),
                        detail: "model could not be checked while Ollama is offline".to_string(),
                    });
                }
            },
            Err(e) => {
                checks.push(DiagnosticCheck {
                    status: "FAIL".to_string(),
                    name: "api".to_string(),
                    detail: e.to_string(),
                });
                checks.push(DiagnosticCheck {
                    status: "WARN".to_string(),
                    name: "model".to_string(),
                    detail: "model could not be checked while Ollama is offline".to_string(),
                });
            }
        }

        DiagnosticReport::new(checks)
    }
}
