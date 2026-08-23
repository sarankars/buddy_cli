use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use tempfile::tempdir;

use buddy::config::{BuddyConfig, ConfigStore};
use buddy::paths::AppPaths;

#[test]
fn test_paths_discovery_and_directories() {
    let dir = tempdir().unwrap();
    let paths = AppPaths::new(dir.path());

    paths.ensure_directories().unwrap();
    assert!(paths.root.is_dir());
    assert!(paths.runtimes_dir().is_dir());
    assert!(paths.models_dir().is_dir());
    assert!(paths.downloads_dir().is_dir());
    assert!(paths.updates_dir().is_dir());
    assert!(paths.logs_dir().is_dir());
}

#[test]
fn test_paths_environment_override() {
    let mut env = HashMap::new();
    env.insert("BUDDY_HOME".to_string(), "/custom/test/home".to_string());
    let paths = AppPaths::discover_with(None, Some(&env), None);
    assert_eq!(paths.root, PathBuf::from("/custom/test/home"));
}

#[test]
fn test_paths_platform_locations() {
    let mock_home = Path::new("/mock/user");
    let env = HashMap::new();

    let mac = AppPaths::discover_with(Some("darwin"), Some(&env), Some(mock_home));
    assert_eq!(
        mac.root,
        PathBuf::from("/mock/user/Library/Application Support/Buddy")
    );

    let linux = AppPaths::discover_with(Some("linux"), Some(&env), Some(mock_home));
    assert_eq!(linux.root, PathBuf::from("/mock/user/.local/share/buddy"));

    let win = AppPaths::discover_with(Some("win32"), Some(&env), Some(mock_home));
    assert_eq!(win.root, PathBuf::from("/mock/user/AppData/Local/Buddy"));
}

#[test]
fn test_config_store_atomic_save_and_load() {
    let dir = tempdir().unwrap();
    let paths = AppPaths::new(dir.path());
    let store = ConfigStore::new(paths.clone());

    assert_eq!(store.load().unwrap(), None);

    let config = BuddyConfig::new(
        "managed",
        "http://127.0.0.1:11435",
        "qwen2.5:3b-instruct",
        Some("/custom/bin/ollama".to_string()),
        Some("0.32.5".to_string()),
    )
    .unwrap();

    store.save(&config).unwrap();
    let loaded = store.load().unwrap().expect("config should load");
    assert_eq!(loaded, config);

    let raw = fs::read_to_string(paths.config_file()).unwrap();
    assert!(raw.contains("managed"));
    assert!(raw.contains("qwen2.5:3b-instruct"));
}
