import asyncio
import logging
import time
from typing import Dict

from shard_core.database.connection import db_conn
from shard_core.database import installed_apps as installed_apps_db
from shard_core.data_model.app_meta import InstalledApp, Status
from shard_core.service import disk
from shard_core.service.app_tools import (
    docker_start_app,
    docker_stop_app,
    get_app_metadata,
    size_is_compatible,
)
from shard_core.util import signals

log = logging.getLogger(__name__)

last_access_dict: Dict[str, float] = dict()
background_tasks = set()


@signals.on_request_to_app.connect
def ensure_app_is_running(app: InstalledApp):
    if disk.current_disk_usage.disk_space_low:
        return
    global last_access_dict
    last_access_dict[app.name] = time.time()
    task = asyncio.create_task(
        _ensure_app_is_running_async(app.name), name=f"ensure {app.name} is running"
    )
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


async def _ensure_app_is_running_async(app_name: str):
    app_meta = get_app_metadata(app_name)
    if await size_is_compatible(app_meta.minimum_portal_size):
        await docker_start_app(app_name)


async def control_apps():
    async with db_conn() as conn:
        all_apps_rows = await installed_apps_db.get_all(conn)
    installed_apps = [
        InstalledApp.parse_obj(a)
        for a in all_apps_rows
        if a["status"] not in (Status.INSTALLATION_QUEUED, Status.INSTALLING)
    ]
    tasks = [_control_app(app.name) for app in installed_apps]
    await asyncio.gather(*tasks)


async def _control_app(name: str):
    global last_access_dict
    app_meta = get_app_metadata(name)

    if disk.current_disk_usage.disk_space_low:
        await docker_stop_app(name)
        return

    if app_meta.lifecycle.always_on:
        if await size_is_compatible(app_meta.minimum_portal_size):
            await docker_start_app(app_meta.name)
    else:
        last_access = last_access_dict.get(app_meta.name, 0.0)
        idle_time_for_shutdown = app_meta.lifecycle.idle_time_for_shutdown
        if last_access < time.time() - idle_time_for_shutdown:
            await docker_stop_app(app_meta.name)
