"""Construction of Buddy application services."""

from __future__ import annotations

from dataclasses import dataclass

from buddy_cli.config import ConfigStore
from buddy_cli.doctor import Doctor
from buddy_cli.paths import AppPaths
from buddy_cli.provisioning import Provisioner
from buddy_cli.runtime_manager import RuntimeManager
from buddy_cli.updater import Updater


@dataclass(frozen=True)
class Services:
    paths: AppPaths
    config_store: ConfigStore
    runtime_manager: RuntimeManager
    provisioner: Provisioner
    doctor: Doctor
    updater: Updater


def build_services() -> Services:
    paths = AppPaths.discover()
    config_store = ConfigStore(paths)
    runtime_manager = RuntimeManager(paths)
    return Services(
        paths=paths,
        config_store=config_store,
        runtime_manager=runtime_manager,
        provisioner=Provisioner(paths, config_store, runtime_manager),
        doctor=Doctor(paths, config_store, runtime_manager),
        updater=Updater(paths),
    )
