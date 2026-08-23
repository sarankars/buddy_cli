//! Construction of Buddy application services.

use crate::config::ConfigStore;
use crate::doctor::Doctor;
use crate::paths::AppPaths;
use crate::provisioning::Provisioner;
use crate::runtime_manager::RuntimeManager;
use crate::updater::Updater;

pub struct Services {
    pub paths: AppPaths,
    pub config_store: ConfigStore,
    pub runtime_manager: RuntimeManager,
    pub provisioner: Provisioner,
    pub doctor: Doctor,
    pub updater: Updater,
}

pub fn build_services() -> Services {
    let paths = AppPaths::discover();
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
