import asyncio
import json
import logging
import time
from pathlib import Path

import shard_core.data_model.profile
from shard_core.database.connection import db_conn
from shard_core.database import installed_apps as db_installed_apps
from shard_core.service import memory_pressure, pause_metrics
from shard_core.data_model.app_meta import (
    Status,
    AppMeta,
    InstalledApp,
    InstalledAppWithMeta,
)
from shard_core.settings import settings
from shard_core.util import signals
from shard_core.util.misc import throttle
from shard_core.util.subprocess import subprocess, SubprocessError, app_compose_command

log = logging.getLogger(__name__)


def _app_compose(name: str) -> tuple[str, ...]:
    return app_compose_command(get_installed_apps_path() / name)


async def docker_create_app_containers(name: str):
    log.debug(f"creating containers for app {name}")
    await subprocess(*_app_compose(name), "up", "--no-start")


async def get_app_container_state(name: str) -> str:
    """Real docker state of an app's containers: running | paused | exited | missing.

    Reads the daemon rather than the stored app status, so a caller can revive an
    app whose containers changed state out-of-band (crash, OOM, core-upgrade
    converge stop) while the database still says PAUSED or RUNNING.
    """
    try:
        ids_out = await subprocess(*_app_compose(name), "ps", "-a", "-q")
    except SubprocessError:
        return "missing"
    ids = [line.strip() for line in ids_out.splitlines() if line.strip()]
    if not ids:
        return "missing"
    states_out = await subprocess(
        "docker", "inspect", "--format", "{{.State.Status}}", *ids
    )
    states = [line.strip() for line in states_out.splitlines() if line.strip()]
    if any(s == "paused" for s in states):
        return "paused"
    if states and all(s == "running" for s in states):
        return "running"
    return "exited"


async def _compose_up(name: str):
    try:
        await subprocess(*_app_compose(name), "up", "-d")
    except SubprocessError as e:
        if "network" in str(e) and "not found" in str(e):
            log.warning(
                f"stale network reference for app {name=}, recreating containers"
            )
            await subprocess(*_app_compose(name), "down")
            await subprocess(*_app_compose(name), "up", "-d")
        elif "Conflict" in str(e) and "already in use" in str(e):
            log.warning(f"stale containers for app {name=}, removing and recreating")
            await subprocess(*_app_compose(name), "down")
            await subprocess(*_app_compose(name), "up", "-d")
        else:
            raise


async def _mark_running(name: str):
    async with db_conn() as conn:
        await db_installed_apps.update_status(conn, name, Status.RUNNING)
    await signals.on_apps_update.send_async()


@throttle(5)
async def start_app(name: str) -> None:
    """Bring an app up regardless of its current container state (idempotent).

    The single revive primitive for both wake-on-access and the always-on
    control tick. It decides from the real container state, not the stored
    status: a paused stack unfreezes, anything exited/created/missing is brought
    up with compose, and an already-running stack is a no-op. This is what keeps
    an app that exited while the database still says PAUSED from 502-looping
    (issue #185) — the old unpause-only wake path errored on a non-paused
    container and the revive task crashed.
    """
    state = await get_app_container_state(name)
    async with db_conn() as conn:
        app = await db_installed_apps.get_by_name(conn, name)
    db_status = app["status"] if app else None

    if state == "running":
        if db_status != Status.RUNNING:
            log.warning(
                f"app {name=} container is running but db says {db_status=}; reconciling"
            )
            await _mark_running(name)
        return

    if state == "paused":
        if db_status != Status.PAUSED:
            log.warning(
                f"app {name=} container is paused but db says {db_status=}; unpausing"
            )
        log.debug(f"unpausing app {name=}")
        unpause_started = time.monotonic()
        await subprocess(*_app_compose(name), "unpause")
        pause_metrics.record_unpause_latency(
            (time.monotonic() - unpause_started) * 1000
        )
        pause_metrics.record_app_transition(name, Status.PAUSED, Status.RUNNING)
        await _mark_running(name)
        return

    # exited / created / missing
    if db_status in (Status.RUNNING, Status.PAUSED):
        log.warning(
            f"app {name=} container is {state} but db says {db_status=}; starting it"
        )
    log.debug(f"starting app {name=}")
    await _compose_up(name)
    await _mark_running(name)


async def docker_pause_app(name: str):
    """Freeze a RUNNING app's containers and page their memory out to swap."""
    async with db_conn() as conn:
        app = await db_installed_apps.get_by_name(conn, name)
        app_status = app["status"] if app else None
    if app_status == Status.RUNNING:
        log.debug(f"pausing app {name=}")
        pause_started = time.monotonic()
        await subprocess(*_app_compose(name), "pause")
        await memory_pressure.reclaim_compose_stack(name)
        pause_metrics.record_pause_latency((time.monotonic() - pause_started) * 1000)
        pause_metrics.record_app_transition(name, Status.RUNNING, Status.PAUSED)
        async with db_conn() as conn:
            await db_installed_apps.update_status(conn, name, Status.PAUSED)
        await signals.on_apps_update.send_async()
    else:
        log.debug(f"app {name=} has {app_status=}, skipping pause")


async def docker_unpause_app(name: str):
    async with db_conn() as conn:
        app = await db_installed_apps.get_by_name(conn, name)
        app_status = app["status"] if app else None
    if app_status == Status.PAUSED:
        log.debug(f"unpausing app {name=}")
        unpause_started = time.monotonic()
        await subprocess(*_app_compose(name), "unpause")
        pause_metrics.record_unpause_latency(
            (time.monotonic() - unpause_started) * 1000
        )
        pause_metrics.record_app_transition(name, Status.PAUSED, Status.RUNNING)
        async with db_conn() as conn:
            await db_installed_apps.update_status(conn, name, Status.RUNNING)
        await signals.on_apps_update.send_async()
    else:
        log.debug(f"app {name=} has {app_status=}, skipping unpause")


async def docker_stop_app(name: str, set_status: bool = True):
    async with db_conn() as conn:
        app = await db_installed_apps.get_by_name(conn, name)
        app_status = app["status"] if app else None
    if app_status in [Status.RUNNING, Status.PAUSED, Status.UNINSTALLING]:
        if app_status == Status.PAUSED:
            # a frozen container cannot be stopped — unfreeze first
            await subprocess(*_app_compose(name), "unpause")
        await subprocess(*_app_compose(name), "stop")
        if set_status:
            pause_metrics.record_app_transition(
                name, Status(app_status), Status.STOPPED
            )
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
        if app_status == Status.PAUSED:
            # only reachable with force=True (process shutdown) — unfreeze so
            # compose down can stop and remove the containers
            await subprocess(*_app_compose(name), "unpause")
        await subprocess(*_app_compose(name), "down")
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
        log.info("docker image pruning is disabled, skipping")
        return
    await docker_prune_images()


class MetadataNotFound(Exception):
    pass
