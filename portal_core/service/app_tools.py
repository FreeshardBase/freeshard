import asyncio
import json
from pathlib import Path

import gconf
from tinydb import Query

from portal_core.database.database import installed_apps_table
from portal_core.model.app_meta import Status, AppMeta, InstalledApp
from portal_core.util import signals
from portal_core.util.misc import throttle
from portal_core.util.subprocess import subprocess


async def docker_create_app(name: str):
	await subprocess('docker-compose', 'up', '--no-start', cwd=get_installed_apps_path() / name)
	with installed_apps_table() as installed_apps:
		installed_apps.update({'status': Status.STOPPED}, Query().name == name)
	await signals.on_apps_update.send_async()


@throttle(5)
async def docker_start_app(name: str):
	with installed_apps_table() as installed_apps:
		# todo: think more about how to handle different states
		if installed_apps.get(Query().name == name)['status'] \
				not in [Status.STOPPED, Status.RUNNING]:
			return
	await subprocess('docker-compose', 'up', '-d', cwd=get_installed_apps_path() / name)
	with installed_apps_table() as installed_apps:
		installed_apps.update({'status': Status.RUNNING}, Query().name == name)
	await signals.on_apps_update.send_async()


async def docker_stop_app(name: str, set_status: bool = True):
	with installed_apps_table() as installed_apps:
		# todo: think more about how to handle different states
		if installed_apps.get(Query().name == name)['status'] \
				not in [Status.RUNNING, Status.UNINSTALLING]:
			return
	await subprocess('docker-compose', 'stop', cwd=get_installed_apps_path() / name)
	if set_status:
		with installed_apps_table() as installed_apps:
			installed_apps.update({'status': Status.STOPPED}, Query().name == name)
	await signals.on_apps_update.send_async()


async def docker_shutdown_app(name: str, set_status: bool = True):
	with installed_apps_table() as installed_apps:
		# todo: think more about how to handle different states
		if installed_apps.get(Query().name == name)['status'] \
				not in [Status.STOPPED, Status.UNINSTALLING]:
			return
	await subprocess('docker-compose', 'down', cwd=get_installed_apps_path() / name)
	if set_status:
		with installed_apps_table() as installed_apps:
			installed_apps.update({'status': Status.DOWN}, Query().name == name)
	await signals.on_apps_update.send_async()


async def docker_stop_all_apps():
	with installed_apps_table() as installed_apps:
		apps = [InstalledApp.parse_obj(a) for a in installed_apps.all()]
	tasks = [docker_stop_app(app.name) for app in apps]
	await asyncio.gather(*tasks)


async def docker_shutdown_all_apps():
	with installed_apps_table() as installed_apps:
		apps = [InstalledApp.parse_obj(a) for a in installed_apps.all()]
	tasks = [docker_shutdown_app(app.name) for app in apps]
	await asyncio.gather(*tasks)


def get_installed_apps_path() -> Path:
	return Path(gconf.get('path_root')) / 'core' / 'installed_apps'


def get_app_metadata(app_name: str) -> AppMeta:
	app_path = get_installed_apps_path() / app_name
	if not app_path.exists():
		raise NoSuchAppDirectory(app_name)
	with open(app_path / 'app_meta.json') as f:
		return AppMeta(**json.load(f))


class NoSuchAppDirectory(Exception):
	pass
