import logging
import time
from typing import Dict

import docker
from docker import errors as docker_errors
from docker.models.containers import Container

import portal_core.util.signals
from portal_core.database.database import apps_table
from portal_core.model.app_meta import InstalledApp, Lifecycle

log = logging.getLogger(__name__)

last_access_dict: Dict[str, float] = dict()


@portal_core.util.signals.on_request_to_app.connect
def ensure_app_is_running(app: InstalledApp):
	global last_access_dict
	last_access_dict[app.name] = time.time()

	docker_client = docker.from_env()
	try:
		docker_client.containers.get(app.name).start()
	except docker_errors.NotFound:
		log.error(f'No container for app: {app.name}')


async def control_apps():
	global last_access_dict
	docker_client = docker.from_env()
	containers = {c.name: c for c in docker_client.containers.list(all=True)}

	with apps_table() as apps:  # type: Table
		all_apps = [InstalledApp.parse_obj(a) for a in apps.all()]

	for app in all_apps:
		lifecycle = Lifecycle.parse_obj(app.lifecycle)
		try:
			container: Container = containers[app.name]
		except KeyError:
			log.warning(f'container for {app.name} not found')
			continue

		if container.status == 'running' and not lifecycle.always_on:
			last_access = last_access_dict.get(app.name, 0.0)
			idle_time_for_shutdown = lifecycle.idle_time_for_shutdown
			if last_access < time.time() - idle_time_for_shutdown:
				log.debug(f'stopping {app.name} due to inactivity')
				container.stop()

		if container.status == 'created' and lifecycle.always_on:
			log.debug(f'starting {app.name} because it is always on')
			container.start()


class NoSuchApp(Exception):
	pass
