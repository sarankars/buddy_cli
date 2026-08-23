//! Discover, install, and start Ollama runtimes.

use std::env;
use std::fmt;
use std::fs::{self, OpenOptions};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;
use tempfile::Builder;

use crate::archive::extract_archive;
use crate::config::BuddyConfig;
use crate::constants::{DEFAULT_OLLAMA_BASE_URL, MANAGED_OLLAMA_BASE_URL, OLLAMA_RUNTIME_VERSION};
use crate::download::{
    download_verified, sha256_file, DownloadOptions, DownloadProgress, DownloadStatus,
};
use crate::ollama::OllamaClient;
use crate::paths::AppPaths;
use crate::runtime_manifest::{resolve_runtime_spec, RuntimeSpec};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeManagerError(pub String);

impl fmt::Display for RuntimeManagerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl std::error::Error for RuntimeManagerError {}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeSelection {
    pub provider: String,
    pub base_url: String,
    pub executable: Option<PathBuf>,
    pub runtime_version: Option<String>,
}

pub struct RuntimeManager {
    pub paths: AppPaths,
}

impl RuntimeManager {
    pub fn new(paths: AppPaths) -> Self {
        Self { paths }
    }

    pub fn api_is_ready(base_url: &str) -> bool {
        if let Ok(client) = OllamaClient::with_timeout(base_url, Duration::from_secs(1)) {
            client.get_version().is_ok()
        } else {
            false
        }
    }

    pub fn find_system_executable() -> Option<PathBuf> {
        if let Some(path_var) = env::var_os("PATH") {
            for dir in env::split_paths(&path_var) {
                let bin = dir.join(if cfg!(windows) {
                    "ollama.exe"
                } else {
                    "ollama"
                });
                if bin.is_file() {
                    return Some(bin);
                }
            }
        }

        let mut candidates = Vec::new();
        if cfg!(target_os = "macos") {
            candidates.push(PathBuf::from(
                "/Applications/Ollama.app/Contents/Resources/ollama",
            ));
            if let Some(home) = dirs::home_dir() {
                candidates.push(home.join("Applications/Ollama.app/Contents/Resources/ollama"));
            }
        } else if cfg!(target_os = "windows") {
            if let Ok(local_app_data) = env::var("LOCALAPPDATA") {
                candidates.push(PathBuf::from(local_app_data).join("Programs/Ollama/ollama.exe"));
            }
        }

        candidates.into_iter().find(|path| path.is_file())
    }

    pub fn installation_dir(&self, spec: &RuntimeSpec) -> PathBuf {
        self.paths.runtimes_dir().join(spec.installation_name())
    }

    fn find_executable_in_dir(root: &Path) -> Option<PathBuf> {
        let target_name = if cfg!(windows) {
            "ollama.exe"
        } else {
            "ollama"
        };
        let mut matches = Vec::new();

        fn walk(dir: &Path, target: &str, matches: &mut Vec<PathBuf>) {
            if let Ok(entries) = fs::read_dir(dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.is_dir() {
                        walk(&path, target, matches);
                    } else if path.file_name().and_then(|n| n.to_str()) == Some(target) {
                        matches.push(path);
                    }
                }
            }
        }

        walk(root, target_name, &mut matches);
        if matches.is_empty() {
            None
        } else {
            matches.sort_by_key(|p| (p.components().count(), p.to_string_lossy().to_string()));
            Some(matches.remove(0))
        }
    }

    pub fn find_managed_executable(&self) -> Option<PathBuf> {
        let spec = resolve_runtime_spec().ok()?;
        let installation = self.installation_dir(&spec);
        if installation.exists() {
            Self::find_executable_in_dir(&installation)
        } else {
            None
        }
    }

    pub fn install_managed<'a>(
        &self,
        download_progress: Option<DownloadProgress<'a>>,
        mut status_callback: Option<DownloadStatus<'a>>,
    ) -> Result<RuntimeSelection, Box<dyn std::error::Error>> {
        let spec = resolve_runtime_spec().map_err(|e| RuntimeManagerError(e.to_string()))?;
        self.paths.ensure_directories()?;

        let installation = self.installation_dir(&spec);
        if installation.exists() {
            if let Some(existing) = Self::find_executable_in_dir(&installation) {
                return Ok(RuntimeSelection {
                    provider: "managed".to_string(),
                    base_url: MANAGED_OLLAMA_BASE_URL.to_string(),
                    executable: Some(existing),
                    runtime_version: Some(spec.version.to_string()),
                });
            }
        }

        let archive = self.paths.downloads_dir().join(spec.asset_name);
        if archive.exists() {
            if let Ok(current_sha) = sha256_file(&archive) {
                if !current_sha.eq_ignore_ascii_case(spec.sha256) {
                    let _ = fs::remove_file(&archive);
                }
            }
        }

        if !archive.exists() {
            if let Some(ref mut s) = status_callback {
                s(&format!("Downloading Ollama {}", spec.version));
            }

            let download_opts = DownloadOptions {
                progress: download_progress,
                status: status_callback,
                ..Default::default()
            };

            download_verified(&spec.url(), &archive, spec.sha256, download_opts)?;
        }

        let stage_temp = Builder::new()
            .prefix(".ollama-stage-")
            .tempdir_in(self.paths.runtimes_dir())?;
        let staged_path = stage_temp.path().to_path_buf();

        extract_archive(&archive, &staged_path, spec.archive_type)?;

        let staged_executable = Self::find_executable_in_dir(&staged_path).ok_or_else(|| {
            RuntimeManagerError("the Ollama archive did not contain an executable".to_string())
        })?;

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if let Ok(meta) = fs::metadata(&staged_executable) {
                let mut perms = meta.permissions();
                perms.set_mode(perms.mode() | 0o755);
                let _ = fs::set_permissions(&staged_executable, perms);
            }
        }

        let relative_executable = staged_executable
            .strip_prefix(&staged_path)
            .map_err(|e| RuntimeManagerError(e.to_string()))?
            .to_path_buf();

        if installation.exists() {
            let _ = fs::remove_dir_all(&installation);
        }

        let raw_stage_path = stage_temp.keep();
        fs::rename(&raw_stage_path, &installation)?;
        let _ = fs::remove_file(&archive);

        let final_executable = installation.join(relative_executable);

        Ok(RuntimeSelection {
            provider: "managed".to_string(),
            base_url: MANAGED_OLLAMA_BASE_URL.to_string(),
            executable: Some(final_executable),
            runtime_version: Some(spec.version.to_string()),
        })
    }

    pub fn start(&self, selection: &RuntimeSelection) -> Result<(), Box<dyn std::error::Error>> {
        if Self::api_is_ready(&selection.base_url) {
            return Ok(());
        }

        let executable = selection.executable.as_ref().ok_or_else(|| {
            RuntimeManagerError("the configured Ollama executable does not exist".to_string())
        })?;

        if !executable.exists() {
            return Err(Box::new(RuntimeManagerError(
                "the configured Ollama executable does not exist".to_string(),
            )));
        }

        self.paths.ensure_directories()?;

        let mut cmd = Command::new(executable);
        cmd.arg("serve");
        cmd.stdin(Stdio::null());

        let log_file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.paths.ollama_log_file())?;
        cmd.stdout(log_file.try_clone()?);
        cmd.stderr(log_file);

        if selection.provider == "managed" {
            let port = if selection.base_url.contains("11435") {
                "11435"
            } else {
                "11434"
            };
            cmd.env("OLLAMA_HOST", format!("127.0.0.1:{}", port));
            cmd.env("OLLAMA_MODELS", self.paths.models_dir());
        }

        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            unsafe {
                cmd.pre_exec(|| {
                    libc::setsid();
                    Ok(())
                });
            }
        }

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NEW_PROCESS_GROUP: u32 = 0x00000200;
            const DETACHED_PROCESS: u32 = 0x00000008;
            cmd.creation_flags(CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS);
        }

        let child = cmd
            .spawn()
            .map_err(|e| RuntimeManagerError(format!("could not start Ollama: {}", e)))?;

        let pid = child.id();
        let _ = fs::write(self.paths.ollama_pid_file(), format!("{}\n", pid));

        let client = OllamaClient::with_timeout(&selection.base_url, Duration::from_secs(1))
            .map_err(|e| RuntimeManagerError(e.to_string()))?;

        if let Err(e) = client.wait_until_ready(Duration::from_secs(45), Duration::from_millis(250))
        {
            return Err(Box::new(RuntimeManagerError(format!(
                "Ollama did not become ready: {}",
                e
            ))));
        }

        Ok(())
    }

    pub fn selection_from_config(&self, config: &BuddyConfig) -> RuntimeSelection {
        RuntimeSelection {
            provider: config.provider.clone(),
            base_url: config.base_url.clone(),
            executable: config.executable.as_ref().map(PathBuf::from),
            runtime_version: config.runtime_version.clone(),
        }
    }

    pub fn discover(&self, config: Option<&BuddyConfig>) -> Option<RuntimeSelection> {
        if let Some(cfg) = config {
            let configured = self.selection_from_config(cfg);
            if Self::api_is_ready(&configured.base_url) {
                return Some(configured);
            }
            if let Some(ref exe) = configured.executable {
                if exe.exists() {
                    return Some(configured);
                }
            }
        }

        if Self::api_is_ready(DEFAULT_OLLAMA_BASE_URL) {
            return Some(RuntimeSelection {
                provider: "system".to_string(),
                base_url: DEFAULT_OLLAMA_BASE_URL.to_string(),
                executable: Self::find_system_executable(),
                runtime_version: None,
            });
        }

        if let Some(sys_exe) = Self::find_system_executable() {
            return Some(RuntimeSelection {
                provider: "system".to_string(),
                base_url: DEFAULT_OLLAMA_BASE_URL.to_string(),
                executable: Some(sys_exe),
                runtime_version: None,
            });
        }

        if let Some(managed_exe) = self.find_managed_executable() {
            return Some(RuntimeSelection {
                provider: "managed".to_string(),
                base_url: MANAGED_OLLAMA_BASE_URL.to_string(),
                executable: Some(managed_exe),
                runtime_version: Some(OLLAMA_RUNTIME_VERSION.to_string()),
            });
        }

        None
    }
}
