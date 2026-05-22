import asyncio
import json
import logging
from pathlib import Path

from python_on_whales import DockerClient
from python_on_whales.exceptions import DockerException

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

log = logging.getLogger(__name__)


async def docker_create_app_containers(name: str):
    log.debug(f"creating containers for app {name}")
    client = DockerClient(compose_project_directory=get_installed_apps_path() / name)
    await asyncio.to_thread(client.compose.up, start=False)


@throttle(5)
async def docker_start_app(name: str):
    async with db_conn() as conn:
        app = await db_installed_apps.get_by_name(conn, name)
        app_status = app["status"] if app else None

    if app_status in [Status.STOPPED, Status.RUNNING, Status.DOWN]:
        log.debug(f"starting app {name=}")
        client = DockerClient(compose_project_directory=get_installed_apps_path() / name)
        try:
            await asyncio.to_thread(client.compose.up, detach=True)
        except DockerException as e:
            if "network" in str(e) and "not found" in str(e):
                log.warning(
                    f"stale network reference for app {name=}, recreating containers"
                )
                await asyncio.to_thread(client.compose.down)
                await asyncio.to_thread(client.compose.up, detach=True)
            elif "Conflict" in str(e) and "already in use" in str(e):
                log.warning(
                    f"stale containers for app {name=}, removing and recreating"
                )
                await asyncio.to_thread(client.compose.down)
                await asyncio.to_thread(client.compose.up, detach=True)
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
        client = DockerClient(compose_project_directory=get_installed_apps_path() / name)
        await asyncio.to_thread(client.compose.stop)
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
        client = DockerClient(compose_project_directory=get_installed_apps_path() / name)
        await asyncio.to_thread(client.compose.down)
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
    filters = {"until": f"{settings().apps.pruning.max_age}h"} if apply_filter else {}
    try:
        output = await asyncio.to_thread(
            DockerClient().image.prune, all=True, filters=filters
        )
    except DockerException as e:
        log.error(f"failed to prune docker images: {e}")
        return
    lines = output.splitlines()
    log.info(f"docker images pruned, {lines[-1]}")
    return lines[-1]


async def scheduled_docker_prune_images():
    if not settings().apps.pruning.enabled:
        log.info("docker image pruning is disabled, skipping")
        return
    await docker_prune_images()


class MetadataNotFound(Exception):
    pass
