import asyncio
import json
import logging
from pathlib import Path

import shard_core.data_model.profile
from shard_core.database.connection import db_conn
from shard_core.database import installed_apps as db_installed_apps
from shard_core.data_model.app_meta import (
    Status,
    AppMeta,
    InstalledApp,
    InstalledAppWithMeta,
)
from shard_core.settings import settings
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
    async with db_conn() as conn:
        app = await db_installed_apps.get_by_name(conn, name)
        app_status = app["status"] if app else None

    if app_status in [Status.STOPPED, Status.RUNNING, Status.DOWN]:
        log.debug(f"starting app {name=}")
        try:
            await subprocess(
                "docker-compose", "up", "-d", cwd=get_installed_apps_path() / name
            )
        except SubprocessError as e:
            if "network" in str(e) and "not found" in str(e):
                log.warning(
                    f"stale network reference for app {name=}, recreating containers"
                )
                await subprocess(
                    "docker-compose", "down", cwd=get_installed_apps_path() / name
                )
                await subprocess(
                    "docker-compose", "up", "-d", cwd=get_installed_apps_path() / name
                )
            else:
                raise
        async with db_conn() as conn:
            await db_installed_apps.update_status(conn, name, Status.RUNNING)
        await signals.on_apps_update.send_async()
    else:
        log.debug(f"app {name=} has status {app_status}, skipping start")


async def docker_stop_app(name: str, set_status: bool = True):
    async with db_conn() as conn:
        app = await db_installed_apps.get_by_name(conn, name)
        app_status = app["status"] if app else None
    if app_status in [Status.RUNNING, Status.UNINSTALLING]:
        await subprocess("docker-compose", "stop", cwd=get_installed_apps_path() / name)
        if set_status:
            async with db_conn() as conn:
                await db_installed_apps.update_status(conn, name, Status.STOPPED)
        await signals.on_apps_update.send_async()
    else:
        log.debug(f"app {name=} has {app_status=}, skipping stop")


async def docker_shutdown_app(name: str, set_status: bool = True, force: bool = False):
    async with db_conn() as conn:
        app = await db_installed_apps.get_by_name(conn, name)
        app_status = app["status"] if app else None
    if force or app_status in [Status.STOPPED, Status.UNINSTALLING]:
        await subprocess("docker-compose", "down", cwd=get_installed_apps_path() / name)
        if set_status:
            async with db_conn() as conn:
                await db_installed_apps.update_status(conn, name, Status.DOWN)
        await signals.on_apps_update.send_async()
    else:
        log.debug(f"app {name=} has {app_status=}, skipping shutdown")


async def docker_stop_all_apps():
    async with db_conn() as conn:
        all_apps = await db_installed_apps.get_all(conn)
    apps = [InstalledApp.model_validate(a) for a in all_apps]
    tasks = [docker_stop_app(app.name) for app in apps]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for app, result in zip(apps, results):
        if isinstance(result, Exception):
            log.error(f"Error stopping app {app.name}: {result}")


async def docker_shutdown_all_apps(force: bool = False):
    async with db_conn() as conn:
        all_apps = await db_installed_apps.get_all(conn)
    apps = [InstalledApp.model_validate(a) for a in all_apps]
    tasks = [docker_shutdown_app(app.name, force=force) for app in apps]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for app, result in zip(apps, results):
        if isinstance(result, Exception):
            log.error(f"Error shutting down app {app.name}: {result}")


def get_installed_apps_path() -> Path:
    return Path(settings().path_root) / "core" / "installed_apps"


def get_app_metadata(app_name: str) -> AppMeta:
    app_path = get_installed_apps_path() / app_name
    if not app_path.exists():
        raise MetadataNotFound(app_name)
    try:
        with open(app_path / "app_meta.json") as f:
            return AppMeta.model_validate(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        raise MetadataNotFound(app_name)


async def size_is_compatible(app_size) -> bool:
    try:
        profile = await shard_core.data_model.profile.get_profile()
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
    return InstalledAppWithMeta(**installed_app.model_dump(), meta=metadata)


async def docker_prune_images(apply_filter=True):
    command = ["docker", "image", "prune", "-fa"]
    if apply_filter:
        command.extend(["--filter", f"until={settings().apps.pruning.max_age}h"])
    try:
        stdout = await subprocess(*command)
    except SubprocessError as e:
        log.error(f"failed to prune docker images: {e}")
        return
    lines = stdout.splitlines()
    log.info(f"docker images pruned, {lines[-1]}")
    return lines[-1]


async def scheduled_docker_prune_images():
    if not settings().apps.pruning.enabled:
        log.debug("docker image pruning is disabled, skipping")
        return
    await docker_prune_images()


class MetadataNotFound(Exception):
    pass
