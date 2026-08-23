//! End-to-end setup orchestration.

use std::fmt;

use crate::config::{BuddyConfig, ConfigStore};
use crate::constants::MODEL_DOWNLOAD_ESTIMATE_BYTES;
use crate::download::DownloadProgress;
use crate::enhancer::OllamaEnhancer;
use crate::ollama::{ModelProgress, OllamaClient};
use crate::paths::AppPaths;
use crate::runtime_manager::RuntimeManager;
use crate::runtime_manifest::{format_bytes, resolve_runtime_spec};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProvisioningError {
    Cancelled(String),
    Failure(String),
}

impl fmt::Display for ProvisioningError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Cancelled(msg) => write!(f, "{}", msg),
            Self::Failure(msg) => write!(f, "{}", msg),
        }
    }
}

impl std::error::Error for ProvisioningError {}

pub type Confirm<'a> = Box<dyn FnMut(&str, bool) -> Result<bool, ProvisioningError> + 'a>;
pub type Emit<'a> = Box<dyn FnMut(&str) + 'a>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SetupResult {
    pub config: BuddyConfig,
    pub installed_runtime: bool,
    pub installed_model: bool,
}

pub struct Provisioner {
    pub paths: AppPaths,
    pub config_store: ConfigStore,
    pub runtime_manager: RuntimeManager,
}

impl Provisioner {
    pub const FREE_SPACE_BUFFER_BYTES: u64 = 500_000_000;

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

    pub fn plan(&self, model: &str) -> Vec<String> {
        let mut messages = Vec::new();
        let config = match self.config_store.load() {
            Ok(cfg) => cfg,
            Err(e) => {
                messages.push(format!("Existing configuration is invalid: {}", e));
                None
            }
        };

        let selection = self.runtime_manager.discover(config.as_ref());
        if selection.is_none() {
            if let Ok(spec) = resolve_runtime_spec() {
                messages.push(format!(
                    "Download Buddy-managed Ollama {} ({})",
                    spec.version,
                    format_bytes(spec.size)
                ));
                messages.push(format!(
                    "Install the runtime under {}",
                    self.paths.runtimes_dir().display()
                ));
                messages.push(format!(
                    "Download model {} (approximately {})",
                    model,
                    format_bytes(MODEL_DOWNLOAD_ESTIMATE_BYTES)
                ));
            }
        } else if let Some(sel) = selection {
            messages.push(format!("Use {} Ollama at {}", sel.provider, sel.base_url));
            if RuntimeManager::api_is_ready(&sel.base_url) {
                if let Ok(client) = OllamaClient::new(&sel.base_url) {
                    if client.has_model(model) {
                        messages.push(format!("Reuse installed model {}", model));
                    } else {
                        messages.push(format!("Download missing model {}", model));
                    }
                } else {
                    messages.push(format!("Verify or download model {}", model));
                }
            } else {
                messages.push("Start Ollama and verify its local API".to_string());
                messages.push(format!("Verify or download model {}", model));
            }
        }

        messages.push("Run an enhancement smoke test and save configuration".to_string());
        messages
    }

    fn check_available_space(&self, required_space: u64) -> Result<(), ProvisioningError> {
        #[cfg(not(unix))]
        let _ = required_space;

        #[cfg(unix)]
        {
            use std::ffi::CString;
            use std::mem::MaybeUninit;

            let path_str = self.paths.root.to_string_lossy().to_string();
            let c_path = CString::new(path_str.as_bytes())
                .map_err(|_| ProvisioningError::Failure("invalid path for statvfs".to_string()))?;

            unsafe {
                let mut stat = MaybeUninit::<libc::statvfs>::uninit();
                if libc::statvfs(c_path.as_ptr(), stat.as_mut_ptr()) == 0 {
                    let stat = stat.assume_init();
                    let free_space = u64::from(stat.f_bavail).saturating_mul(stat.f_frsize);
                    if free_space < required_space {
                        return Err(ProvisioningError::Failure(format!(
                            "not enough free space for Ollama and the enhancement model: need approximately {}, have {}",
                            format_bytes(required_space),
                            format_bytes(free_space)
                        )));
                    }
                }
            }
        }

        Ok(())
    }

    pub fn setup<'a>(
        &self,
        model: &str,
        mut confirm: Confirm<'a>,
        mut emit: Emit<'a>,
        download_progress: Option<DownloadProgress<'a>>,
        model_progress: Option<ModelProgress<'a>>,
    ) -> Result<SetupResult, Box<dyn std::error::Error>> {
        self.paths.ensure_directories()?;

        let existing_config = match self.config_store.load() {
            Ok(cfg) => cfg,
            Err(e) => {
                emit(&format!("Ignoring invalid configuration: {}", e));
                None
            }
        };

        let mut selection = self.runtime_manager.discover(existing_config.as_ref());
        let mut installed_runtime = false;

        if selection.is_none() {
            let spec =
                resolve_runtime_spec().map_err(|e| ProvisioningError::Failure(e.to_string()))?;

            let runtime_working_space = if spec.operating_system == "windows" {
                (spec.size * 2).max(4_000_000_000)
            } else {
                spec.size * 2
            };

            let required_space = runtime_working_space
                + MODEL_DOWNLOAD_ESTIMATE_BYTES
                + Self::FREE_SPACE_BUFFER_BYTES;

            self.check_available_space(required_space)?;

            let msg = format!(
                "Download Ollama {} ({}) into {}?",
                spec.version,
                format_bytes(spec.size),
                self.paths.runtimes_dir().display()
            );

            if !confirm(&msg, false)? {
                return Err(Box::new(ProvisioningError::Cancelled(
                    "Ollama runtime download was declined".to_string(),
                )));
            }

            let sel = self
                .runtime_manager
                .install_managed(download_progress, Some(Box::new(|status| emit(status))))?;

            installed_runtime = true;
            selection = Some(sel);
            emit("Ollama runtime is installed and verified");
        } else if let Some(ref sel) = selection {
            emit(&format!(
                "Using {} Ollama at {}",
                sel.provider, sel.base_url
            ));
        }

        let sel = selection.unwrap();
        self.runtime_manager.start(&sel)?;

        let client = OllamaClient::new(&sel.base_url)
            .map_err(|e| ProvisioningError::Failure(e.to_string()))?;

        let version = client
            .get_version()
            .map_err(|e| ProvisioningError::Failure(e.to_string()))?;

        emit(&format!("Ollama {} is running", version.version));
        let has_model = client.has_model(model);
        let mut installed_model = false;

        if !has_model {
            let msg = format!(
                "Download model {} (approximately {})?",
                model,
                format_bytes(MODEL_DOWNLOAD_ESTIMATE_BYTES)
            );

            if !confirm(&msg, false)? {
                return Err(Box::new(ProvisioningError::Cancelled(
                    "model download was declined".to_string(),
                )));
            }

            emit(&format!("Downloading model {}", model));
            client.pull_model(model, model_progress).map_err(|e| {
                ProvisioningError::Failure(format!("could not download {}: {}", model, e))
            })?;

            installed_model = true;
            emit(&format!("Model {} is installed", model));
        } else {
            emit(&format!("Model {} is already installed", model));
        }

        let enhancer = OllamaEnhancer::new(client.clone(), model);
        enhancer.enhance("say hello more clearly").map_err(|e| {
            ProvisioningError::Failure(format!("enhancement smoke test failed: {}", e))
        })?;

        let config = BuddyConfig::new(
            &sel.provider,
            &sel.base_url,
            model,
            sel.executable
                .as_ref()
                .map(|p| p.to_string_lossy().to_string()),
            sel.runtime_version.clone(),
        )
        .map_err(|e| ProvisioningError::Failure(e.to_string()))?;

        self.config_store.save(&config)?;
        emit("Enhancement smoke test passed");

        Ok(SetupResult {
            config,
            installed_runtime,
            installed_model,
        })
    }
}
