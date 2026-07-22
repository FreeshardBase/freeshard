import asyncio
import logging
import time
from typing import Dict, List

from shard_core.database.connection import db_conn
from shard_core.database import installed_apps as db_installed_apps
from shard_core.data_model.app_meta import InstalledApp, Status
from shard_core.service import disk, memory_pressure, pause_metrics
from shard_core.service.app_tools import (
    docker_start_app,
    docker_stop_app,
    docker_pause_app,
    docker_unpause_app,
    get_app_metadata,
    size_is_compatible,
)
from shard_core.settings import settings
from shard_core.util import signals

log = logging.getLogger(__name__)

last_access_dict: Dict[str, float] = dict()
background_tasks = set()

# Pressure demotion never touches an app accessed within this window (seconds).
RECENT_ACCESS_GRACE = 5


@signals.on_request_to_app.connect
async def ensure_app_is_running(app: InstalledApp):
    if disk.current_disk_usage.disk_space_low:
        return
    app_meta = get_app_metadata(app.name)
    if await size_is_compatible(app_meta.minimum_portal_size):
        global last_access_dict
        last_access_dict[app.name] = time.time()
        # PAUSED wakes via unpause (ms to ~2s), everything else via the legacy
        # start path. Calling docker_unpause_app directly also dodges the
        # per-app 5s throttle on docker_start_app, which would silently drop
        # the wake. This dispatch stays active even with pause_enabled=false,
        # so already-paused apps still wake after a backout.
        if app.status == Status.PAUSED:
            coro = docker_unpause_app(app.name)
        else:
            coro = docker_start_app(app.name)
        task = asyncio.create_task(coro, name=f"ensure {app.name} is running")
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)


async def control_apps():
    lifecycle_settings = settings().apps.lifecycle
    pause_enabled = lifecycle_settings.pause_enabled
    psi = memory_pressure.read_memory_pressure() if pause_enabled else 0.0
    pressure_high = pause_enabled and psi > lifecycle_settings.psi_threshold
    if pause_enabled:
        pause_metrics.record_psi_snapshot(psi)

    async with db_conn() as conn:
        all_apps = await db_installed_apps.get_all(conn)
    installed_apps = [
        InstalledApp.model_validate(a)
        for a in all_apps
        if a["status"] not in (Status.INSTALLATION_QUEUED, Status.INSTALLING)
    ]
    tasks = [_control_app_time(app, pause_enabled) for app in installed_apps]
    await asyncio.gather(*tasks)
    if pressure_high:
        log.info(f"memory pressure high (PSI some avg10 = {psi}), demoting LRU app")
        await _demote_lru(installed_apps)


async def _control_app_time(app: InstalledApp, pause_enabled: bool):
    app_meta = get_app_metadata(app.name)

    # Low disk stops every app, always_on included — a paused or running app
    # can otherwise fill the disk completely.
    if disk.current_disk_usage.disk_space_low:
        await docker_stop_app(app.name)
        return

    if app_meta.lifecycle.always_on:
        if app.status != Status.RUNNING and await size_is_compatible(
            app_meta.minimum_portal_size
        ):
            await docker_start_app(app.name)
        return

    idle = time.time() - last_access_dict.get(app.name, 0.0)
    t2 = (
        app_meta.lifecycle.idle_for_stop
        or settings().apps.lifecycle.default_idle_for_stop
    )

    # Feature flag off, or app opts out of the pause tier: legacy stop-only.
    if not pause_enabled or app_meta.lifecycle.skip_pause:
        if app.status == Status.RUNNING and idle >= t2:
            await docker_stop_app(app.name)
        return

    t1 = (
        app_meta.lifecycle.idle_for_pause
        or settings().apps.lifecycle.default_idle_for_pause
    )
    if app.status == Status.RUNNING and idle >= t1:
        await docker_pause_app(app.name)
    elif app.status == Status.PAUSED and idle >= t2:
        await docker_stop_app(app.name)


async def _demote_lru(apps: List[InstalledApp]):
    """Demote the least-recently-used demotable app one tier.

    RUNNING apps are considered first: pausing has less user impact than
    stopping, and paused apps mostly have older last-access times — a single
    LRU sort across both tiers would systematically stop paused apps instead.
    Only when nothing is left to pause does the LRU paused app get stopped.

    One demotion per control cycle: the next cycle re-reads PSI and demotes
    again only if pressure is still high, so a spike frees memory gradually
    instead of stopping everything at once.
    """
    running = []
    paused = []
    for app in apps:
        app_meta = get_app_metadata(app.name)
        if app_meta.lifecycle.always_on:
            continue
        if time.time() - last_access_dict.get(app.name, 0.0) <= RECENT_ACCESS_GRACE:
            continue
        if app.status == Status.RUNNING:
            running.append(app)
        elif app.status == Status.PAUSED:
            paused.append(app)

    def lru(candidates: List[InstalledApp]) -> InstalledApp:
        return min(candidates, key=lambda app: last_access_dict.get(app.name, 0.0))

    if running:
        victim = lru(running)
        if get_app_metadata(victim.name).lifecycle.skip_pause:
            await docker_stop_app(victim.name)
        else:
            await docker_pause_app(victim.name)
    elif paused:
        await docker_stop_app(lru(paused).name)
