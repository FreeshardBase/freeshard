import logging
import time
from typing import Dict

import docker
from docker import errors as docker_errors
from docker.models.containers import Container
from tinydb.table import Table

import portal_core.util.signals
from portal_core.database.database import apps_table
from portal_core.model.app import InstalledApp, Lifecycle

log = logging.getLogger(__name__)

last_access_dict: Dict[str, float] = dict()


@portal_core.util.signals.on_request_to_app.connect
def ensure_app_is_running(app: InstalledApp):
	global last_access_dict
	last_access_dict[app.name] = time.time()

	docker_client = docker.from_env()
	try:
		docker_client.containers.get(app.name).start()
	except docker_errors.NotFound as e:
		raise NoSuchApp(app.name) from e


async def stop_apps():
	global last_access_dict
	docker_client = docker.from_env()
	containers = {c.name: c for c in docker_client.containers.list(all=True)}

	with apps_table() as apps:  # type: Table
		for app in [InstalledApp(**a) for a in apps.all()]:
			lifecycle = Lifecycle(**app.lifecycle)
			try:
				container: Container = containers[app.name]
			except KeyError:
				log.debug(f'container for {app.name} not found')
				continue

			if container.status == 'running' and not lifecycle.always_on:
				last_access = last_access_dict.get(app.name, 0.0)
				idle_time_for_shutdown = lifecycle.idle_time_for_shutdown
				if last_access < time.time() - idle_time_for_shutdown:
					log.debug(f'stopping {app.name} due to inactivity')
					container.stop()


class NoSuchApp(Exception):
	pass
