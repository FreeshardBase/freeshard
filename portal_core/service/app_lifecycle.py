import asyncio
import logging
import time
from typing import Dict

import portal_core.util.signals
from portal_core.database.database import apps_table
from portal_core.model.app_meta import InstalledApp
from portal_core.service.app_tools import docker_start_app, docker_stop_app, get_installed_apps, get_app_metadata
from tinydb.table import Table

log = logging.getLogger(__name__)

last_access_dict: Dict[str, float] = dict()


@portal_core.util.signals.on_request_to_app.connect
async def ensure_app_is_running(app: InstalledApp):
	global last_access_dict
	last_access_dict[app.name] = time.time()
	await docker_start_app(app.name)


async def control_apps():
	all_apps = get_installed_apps()
	tasks = [control_app(app) for app in all_apps]
	await asyncio.gather(*tasks)


async def control_app(name: str):
	global last_access_dict
	meta = get_app_metadata(name)
	if meta.lifecycle.always_on:
		await docker_start_app(meta.name)
	else:
		last_access = last_access_dict.get(meta.name, 0.0)
		idle_time_for_shutdown = meta.lifecycle.idle_time_for_shutdown
		if last_access < time.time() - idle_time_for_shutdown:
			await docker_stop_app(meta.name)


class AppNotStarted(Exception):
	pass
