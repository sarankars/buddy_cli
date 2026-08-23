use tempfile::tempdir;

use buddy::cli::run_cli_with_args;
use buddy::config::ConfigStore;
use buddy::doctor::Doctor;
use buddy::paths::AppPaths;
use buddy::provisioning::Provisioner;
use buddy::runtime_manager::RuntimeManager;
use buddy::services::Services;
use buddy::updater::Updater;

fn test_services(root: &std::path::Path) -> Services {
    let paths = AppPaths::new(root);
    let config_store = ConfigStore::new(paths.clone());
    let runtime_manager = RuntimeManager::new(paths.clone());
    let provisioner = Provisioner::new(
        paths.clone(),
        ConfigStore::new(paths.clone()),
        RuntimeManager::new(paths.clone()),
    );
    let doctor = Doctor::new(
        paths.clone(),
        ConfigStore::new(paths.clone()),
        RuntimeManager::new(paths.clone()),
    );
    let updater = Updater::new(paths.clone());

    Services {
        paths,
        config_store,
        runtime_manager,
        provisioner,
        doctor,
        updater,
    }
}

#[test]
fn test_cli_enhance_offline() {
    let dir = tempdir().unwrap();
    let services = test_services(dir.path());

    let exit_code = run_cli_with_args(
        vec![
            "buddy",
            "enhance",
            "--offline",
            "make",
            "the",
            "readme",
            "better",
        ],
        &services,
    );

    assert_eq!(exit_code, 0);
}

#[test]
fn test_cli_setup_dry_run() {
    let dir = tempdir().unwrap();
    let services = test_services(dir.path());

    let exit_code = run_cli_with_args(vec!["buddy", "setup", "--dry-run"], &services);

    assert_eq!(exit_code, 0);
}

#[test]
fn test_cli_doctor_json() {
    let dir = tempdir().unwrap();
    let services = test_services(dir.path());

    let exit_code = run_cli_with_args(vec!["buddy", "doctor", "--json"], &services);

    // Unconfigured environment returns 1 for doctor
    assert_eq!(exit_code, 1);
}
