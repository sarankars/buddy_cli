//! Platform-specific application paths.

use std::collections::HashMap;
use std::env;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AppPaths {
    pub root: PathBuf,
}

impl AppPaths {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    pub fn config_file(&self) -> PathBuf {
        self.root.join("config.json")
    }

    pub fn runtimes_dir(&self) -> PathBuf {
        self.root.join("runtimes")
    }

    pub fn models_dir(&self) -> PathBuf {
        self.root.join("models")
    }

    pub fn downloads_dir(&self) -> PathBuf {
        self.root.join("downloads")
    }

    pub fn updates_dir(&self) -> PathBuf {
        self.root.join("updates")
    }

    pub fn logs_dir(&self) -> PathBuf {
        self.root.join("logs")
    }

    pub fn ollama_log_file(&self) -> PathBuf {
        self.logs_dir().join("ollama.log")
    }

    pub fn ollama_pid_file(&self) -> PathBuf {
        self.root.join("ollama.pid")
    }

    pub fn ensure_directories(&self) -> io::Result<()> {
        for dir in &[
            &self.root,
            &self.runtimes_dir(),
            &self.models_dir(),
            &self.downloads_dir(),
            &self.updates_dir(),
            &self.logs_dir(),
        ] {
            fs::create_dir_all(dir)?;
        }
        Ok(())
    }

    pub fn discover() -> Self {
        Self::discover_with(None, None, None)
    }

    pub fn discover_with(
        platform_name: Option<&str>,
        environment: Option<&HashMap<String, String>>,
        home: Option<&Path>,
    ) -> Self {
        if let Some(env_map) = environment {
            if let Some(override_path) = env_map.get("BUDDY_HOME") {
                if !override_path.trim().is_empty() {
                    return Self::new(shellexpand_tilde(override_path));
                }
            }
        } else if let Ok(override_path) = env::var("BUDDY_HOME") {
            if !override_path.trim().is_empty() {
                return Self::new(shellexpand_tilde(&override_path));
            }
        }

        let current_platform = platform_name.unwrap_or(if cfg!(target_os = "macos") {
            "darwin"
        } else if cfg!(target_os = "windows") {
            "win32"
        } else {
            "linux"
        });

        let user_home = match home {
            Some(h) => h.to_path_buf(),
            None => dirs::home_dir().unwrap_or_else(|| PathBuf::from(".")),
        };

        let root = if current_platform == "darwin" || current_platform.starts_with("mac") {
            user_home
                .join("Library")
                .join("Application Support")
                .join("Buddy")
        } else if current_platform == "win32" || current_platform.starts_with("win") {
            let local_app_data = if let Some(env_map) = environment {
                env_map.get("LOCALAPPDATA").cloned()
            } else {
                env::var("LOCALAPPDATA").ok()
            };

            if let Some(app_data) = local_app_data {
                if !app_data.trim().is_empty() {
                    PathBuf::from(app_data).join("Buddy")
                } else {
                    user_home.join("AppData").join("Local").join("Buddy")
                }
            } else {
                user_home.join("AppData").join("Local").join("Buddy")
            }
        } else {
            let xdg_data_home = if let Some(env_map) = environment {
                env_map.get("XDG_DATA_HOME").cloned()
            } else {
                env::var("XDG_DATA_HOME").ok()
            };

            if let Some(xdg) = xdg_data_home {
                if !xdg.trim().is_empty() {
                    PathBuf::from(xdg).join("buddy")
                } else {
                    user_home.join(".local").join("share").join("buddy")
                }
            } else {
                user_home.join(".local").join("share").join("buddy")
            }
        };

        Self::new(root)
    }
}

fn shellexpand_tilde(path_str: &str) -> PathBuf {
    if let Some(stripped) = path_str.strip_prefix("~/") {
        if let Some(home) = dirs::home_dir() {
            return home.join(stripped);
        }
    }
    PathBuf::from(path_str)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_app_paths_subpaths() {
        let paths = AppPaths::new("/tmp/buddy_test");
        assert_eq!(
            paths.config_file(),
            PathBuf::from("/tmp/buddy_test/config.json")
        );
        assert_eq!(
            paths.runtimes_dir(),
            PathBuf::from("/tmp/buddy_test/runtimes")
        );
        assert_eq!(paths.models_dir(), PathBuf::from("/tmp/buddy_test/models"));
        assert_eq!(
            paths.downloads_dir(),
            PathBuf::from("/tmp/buddy_test/downloads")
        );
        assert_eq!(
            paths.updates_dir(),
            PathBuf::from("/tmp/buddy_test/updates")
        );
        assert_eq!(paths.logs_dir(), PathBuf::from("/tmp/buddy_test/logs"));
        assert_eq!(
            paths.ollama_log_file(),
            PathBuf::from("/tmp/buddy_test/logs/ollama.log")
        );
        assert_eq!(
            paths.ollama_pid_file(),
            PathBuf::from("/tmp/buddy_test/ollama.pid")
        );
    }

    #[test]
    fn test_discover_override() {
        let mut env = HashMap::new();
        env.insert("BUDDY_HOME".to_string(), "/custom/buddy".to_string());
        let paths = AppPaths::discover_with(None, Some(&env), None);
        assert_eq!(paths.root, PathBuf::from("/custom/buddy"));
    }

    #[test]
    fn test_discover_platforms() {
        let home = Path::new("/mock/home");
        let darwin = AppPaths::discover_with(Some("darwin"), Some(&HashMap::new()), Some(home));
        assert_eq!(
            darwin.root,
            PathBuf::from("/mock/home/Library/Application Support/Buddy")
        );

        let linux = AppPaths::discover_with(Some("linux"), Some(&HashMap::new()), Some(home));
        assert_eq!(linux.root, PathBuf::from("/mock/home/.local/share/buddy"));

        let win = AppPaths::discover_with(Some("win32"), Some(&HashMap::new()), Some(home));
        assert_eq!(win.root, PathBuf::from("/mock/home/AppData/Local/Buddy"));
    }
}
