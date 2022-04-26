import logging
import time

import docker
from docker import errors as docker_errors
from tinydb.table import Table

from portal_core.database.database import apps_table
from portal_core.model.app import InstalledApp

log = logging.getLogger(__name__)

last_access_dict = dict()


def ensure_app_is_running(app: InstalledApp):
	global last_access_dict
	last_access_dict[app.name] = time.time()

	docker_client = docker.from_env()
	try:
		docker_client.containers.get(app.name).start()
	except docker_errors.NotFound as e:
		raise NoSuchApp from e


async def stop_apps():
	docker_client = docker.from_env()
	global last_access_dict
	with apps_table() as apps:  # type: Table
		for app in [InstalledApp(**a) for a in apps.all()]:
			try:
				last_access = last_access_dict[app.name]
			except KeyError:
				continue
			if last_access < time.time() - 10:
				log.debug(f'Stopping {app.name} due to inactivity')
				docker_client.containers.get(app.name).stop()
				del last_access_dict[app.name]

class NoSuchApp(Exception):
	pass