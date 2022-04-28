import logging
import time
from typing import Dict

import docker
import gconf
from docker import errors as docker_errors
from docker.models.containers import Container
from tinydb.table import Table

from portal_core.database.database import apps_table
from portal_core.model.app import InstalledApp

log = logging.getLogger(__name__)

last_access_dict: Dict[str, float] = dict()


def ensure_app_is_running(app: InstalledApp):
	global last_access_dict
	last_access_dict[app.name] = time.time()

	docker_client = docker.from_env()
	try:
		docker_client.containers.get(app.name).start()
	except docker_errors.NotFound as e:
		raise NoSuchApp from e


async def stop_apps():
	global last_access_dict
	docker_client = docker.from_env()
	containers = {c.name: c for c in docker_client.containers.list()}

	with apps_table() as apps:  # type: Table
		for app in [InstalledApp(**a) for a in apps.all()]:
			try:
				container: Container = containers[app.name]
			except KeyError as e:
				log.error(f'no container found for app {app.name}')
				continue

			if container.status == 'running':
				last_access = last_access_dict.get(app.name, default=0.0)
				if last_access < time.time() - gconf.get('apps.lifecycle.default_idle_time_for_shutdown'):
					log.debug(f'Stopping {app.name} due to inactivity')
					container.stop()


class NoSuchApp(Exception):
	pass
