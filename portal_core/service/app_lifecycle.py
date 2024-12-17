import asyncio
import logging
import time
from typing import Dict

from sqlmodel import select

from portal_core.database.database import session
from portal_core.database.models import InstalledApp, Status
from portal_core.service import disk
from portal_core.service.app_tools import docker_start_app, docker_stop_app, get_app_metadata, size_is_compatible
from portal_core.util import signals

log = logging.getLogger(__name__)

last_access_dict: Dict[str, float] = dict()


@signals.on_request_to_app.connect
def ensure_app_is_running(app: InstalledApp):
	if disk.current_disk_usage.disk_space_low:
		return
	app_meta = get_app_metadata(app.name)
	if size_is_compatible(app_meta.minimum_portal_size):
		global last_access_dict
		last_access_dict[app.name] = time.time()
		asyncio.create_task(docker_start_app(app.name), name=f'ensure {app.name} is running')


async def control_apps():
	with session() as session_:
		statement = select(InstalledApp) \
			.where(InstalledApp.status != Status.INSTALLING) \
			.where(InstalledApp.status != Status.INSTALLATION_QUEUED)
		installed_apps = session_.exec(statement).all()

	tasks = [_control_app(app.name) for app in installed_apps]
	await asyncio.gather(*tasks)


async def _control_app(name: str):
	global last_access_dict
	app_meta = get_app_metadata(name)

	if disk.current_disk_usage.disk_space_low:
		await docker_stop_app(name)
		return

	if app_meta.lifecycle.always_on:
		if size_is_compatible(app_meta.minimum_portal_size):
			await docker_start_app(app_meta.name)
	else:
		last_access = last_access_dict.get(app_meta.name, 0.0)
		idle_time_for_shutdown = app_meta.lifecycle.idle_time_for_shutdown
		if last_access < time.time() - idle_time_for_shutdown:
			await docker_stop_app(app_meta.name)
