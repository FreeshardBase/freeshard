import asyncio
import logging
import time
from typing import Dict

from portal_core.database.database import installed_apps_table
from portal_core.model.app_meta import InstalledApp, Status
from portal_core.service.app_tools import docker_start_app, docker_stop_app, get_app_metadata, size_is_compatible
from portal_core.util import signals

log = logging.getLogger(__name__)

last_access_dict: Dict[str, float] = dict()


@signals.on_request_to_app.connect
async def ensure_app_is_running(app: InstalledApp):
	app_meta = get_app_metadata(app.name)
	if size_is_compatible(app_meta.minimum_portal_size):
		global last_access_dict
		last_access_dict[app.name] = time.time()
		# todo: don't wait for this
		await docker_start_app(app.name)


async def control_apps():
	with installed_apps_table() as installed_apps:
		installed_apps = [
			InstalledApp.parse_obj(a)
			for a in installed_apps.all()
			if a['status'] not in (Status.INSTALLATION_QUEUED, Status.INSTALLING)]
	tasks = [_control_app(app.name) for app in installed_apps]
	await asyncio.gather(*tasks)


async def _control_app(name: str):
	global last_access_dict
	app_meta = get_app_metadata(name)

	if app_meta.lifecycle.always_on:
		if size_is_compatible(app_meta.minimum_portal_size):
			await docker_start_app(app_meta.name)
	else:
		last_access = last_access_dict.get(app_meta.name, 0.0)
		idle_time_for_shutdown = app_meta.lifecycle.idle_time_for_shutdown
		if last_access < time.time() - idle_time_for_shutdown:
			await docker_stop_app(app_meta.name)
