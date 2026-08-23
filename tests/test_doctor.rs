use tempfile::tempdir;

use buddy::config::ConfigStore;
use buddy::doctor::Doctor;
use buddy::paths::AppPaths;
use buddy::runtime_manager::RuntimeManager;

#[test]
fn test_doctor_runs_and_reports() {
    let dir = tempdir().unwrap();
    let paths = AppPaths::new(dir.path());
    let config_store = ConfigStore::new(paths.clone());
    let runtime_manager = RuntimeManager::new(paths.clone());

    let doctor = Doctor::new(paths, config_store, runtime_manager);
    let report = doctor.run();

    // Since we are unconfigured in an isolated tempdir, healthy will be false because configuration is missing
    assert!(!report.healthy);

    let check_names: Vec<&str> = report.checks.iter().map(|c| c.name.as_str()).collect();
    assert!(check_names.contains(&"platform"));
    assert!(check_names.contains(&"storage"));
    assert!(check_names.contains(&"configuration"));
    assert!(check_names.contains(&"runtime"));
    assert!(check_names.contains(&"api"));
    assert!(check_names.contains(&"model"));
}
