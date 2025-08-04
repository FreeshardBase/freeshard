import asyncio
import json
import logging
from pathlib import Path

import gconf
from tinydb import Query

import shard_core.data_model.profile
from shard_core.database.database import installed_apps_table
from shard_core.data_model.app_meta import (
    Status,
    AppMeta,
    InstalledApp,
    InstalledAppWithMeta,
)
from shard_core.util import signals
from shard_core.util.misc import throttle
from shard_core.util.subprocess import subprocess, SubprocessError

log = logging.getLogger(__name__)


async def docker_create_app_containers(name: str):
    log.debug(f"creating containers for app {name}")
    await subprocess(
        "docker-compose", "up", "--no-start", cwd=get_installed_apps_path() / name
    )


@throttle(5)
async def docker_start_app(name: str):
    with installed_apps_table() as installed_apps:
        # todo: think more about how to handle different states
        app_status = installed_apps.get(Query().name == name)["status"]

    if app_status in [Status.STOPPED, Status.RUNNING, Status.DOWN]:
        log.debug(f"starting app {name=}")
        await subprocess(
            "docker-compose", "up", "-d", cwd=get_installed_apps_path() / name
        )
        with installed_apps_table() as installed_apps:
            installed_apps.update({"status": Status.RUNNING}, Query().name == name)
        signals.on_apps_update.send()
    else:
        log.debug(f"app {name=} has status {app_status}, skipping start")


async def docker_stop_app(name: str, set_status: bool = True):
    with installed_apps_table() as installed_apps:
        # todo: think more about how to handle different states
        app_status = installed_apps.get(Query().name == name)["status"]
    if app_status in [Status.RUNNING, Status.UNINSTALLING]:
        await subprocess("docker-compose", "stop", cwd=get_installed_apps_path() / name)
        if set_status:
            with installed_apps_table() as installed_apps:
                installed_apps.update({"status": Status.STOPPED}, Query().name == name)
        signals.on_apps_update.send()
    else:
        log.debug(f"app {name=} has {app_status=}, skipping stop")


async def docker_shutdown_app(name: str, set_status: bool = True, force: bool = False):
    with installed_apps_table() as installed_apps:
        # todo: think more about how to handle different states
        app_status = installed_apps.get(Query().name == name)["status"]
    if force or app_status in [Status.STOPPED, Status.UNINSTALLING]:
        await subprocess("docker-compose", "down", cwd=get_installed_apps_path() / name)
        if set_status:
            with installed_apps_table() as installed_apps:
                installed_apps.update({"status": Status.DOWN}, Query().name == name)
        signals.on_apps_update.send()
    else:
        log.debug(f"app {name=} has {app_status=}, skipping shutdown")


async def docker_stop_all_apps():
    with installed_apps_table() as installed_apps:
        apps = [InstalledApp.parse_obj(a) for a in installed_apps.all()]
    tasks = [docker_stop_app(app.name) for app in apps]
    await asyncio.gather(*tasks)


async def docker_shutdown_all_apps(force: bool = False):
    with installed_apps_table() as installed_apps:
        apps = [InstalledApp.parse_obj(a) for a in installed_apps.all()]
    tasks = [docker_shutdown_app(app.name, force=force) for app in apps]
    await asyncio.gather(*tasks)


def get_installed_apps_path() -> Path:
    return Path(gconf.get("path_root")) / "core" / "installed_apps"


def get_app_metadata(app_name: str) -> AppMeta:
    app_path = get_installed_apps_path() / app_name
    if not app_path.exists():
        raise MetadataNotFound(app_name)
    try:
        with open(app_path / "app_meta.json") as f:
            return AppMeta.parse_obj(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        raise MetadataNotFound(app_name)


def size_is_compatible(app_size) -> bool:
    try:
        profile = shard_core.data_model.profile.get_profile()
    except KeyError:
        return False
    if profile is None:
        return True
    vm_size = profile.vm_size
    return vm_size >= app_size


def enrich_installed_app_with_meta(installed_app: InstalledApp) -> InstalledAppWithMeta:
    try:
        metadata = get_app_metadata(installed_app.name)
    except MetadataNotFound:
        metadata = None
    return InstalledAppWithMeta(**installed_app.dict(), meta=metadata)


async def docker_prune_images(apply_filter=True):
    command = ["docker", "image", "prune", "-fa"]
    if apply_filter:
        command.extend(["--filter", f'until={gconf.get("apps.pruning.max_age")}h'])
    try:
        stdout = await subprocess(*command)
    except SubprocessError as e:
        log.error(f"failed to prune docker images: {e}")
        return
    lines = stdout.splitlines()
    log.info(f"docker images pruned, {lines[-1]}")
    return lines[-1]


class MetadataNotFound(Exception):
    pass
