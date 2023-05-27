import asyncio
import logging
import time
from typing import Dict

import portal_core.util.signals
from portal_core.database.database import apps_table
from portal_core.model.app_meta import InstalledApp
from portal_core.service.app_store import get_app_metadata, get_installed_apps_path, get_installed_apps
from portal_core.util.subprocess import subprocess

log = logging.getLogger(__name__)

last_access_dict: Dict[str, float] = dict()


@portal_core.util.signals.on_request_to_app.connect
async def ensure_app_is_running(app: InstalledApp):
	global last_access_dict
	last_access_dict[app.name] = time.time()
	await start_app(app.name)


async def control_apps():
	with apps_table() as apps:  # type: Table
		all_apps = [InstalledApp.parse_obj(a) for a in apps.all()]

	tasks = [control_app(app.name) for app in all_apps]
	await asyncio.gather(*tasks)


async def control_app(name: str):
	global last_access_dict
	meta = get_app_metadata(name)
	if meta.lifecycle.always_on:
		await start_app(meta.name)
	else:
		last_access = last_access_dict.get(meta.name, 0.0)
		idle_time_for_shutdown = meta.lifecycle.idle_time_for_shutdown
		if last_access < time.time() - idle_time_for_shutdown:
			await stop_app(meta.name)


async def start_app(name: str):
	await subprocess('docker-compose', 'up', '-d', cwd=get_installed_apps_path() / name)


async def stop_app(name: str):
	await subprocess('docker-compose', 'stop', cwd=get_installed_apps_path() / name)


async def remove_app(name: str):
	await subprocess('docker-compose', 'down', cwd=get_installed_apps_path() / name)


async def stop_all_apps():
	apps = get_installed_apps()
	tasks = [stop_app(app) for app in apps]
	await asyncio.gather(*tasks)


async def remove_all_apps():
	apps = get_installed_apps()
	tasks = [remove_app(app) for app in apps]
	await asyncio.gather(*tasks)


class AppNotStarted(Exception):
	pass
