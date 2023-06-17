import asyncio
import json
from pathlib import Path
from typing import Set

import gconf
from tinydb import Query

from portal_core.database.database import apps_table
from portal_core.model.app_meta import Status, AppMeta
from portal_core.util import signals
from portal_core.util.misc import throttle
from portal_core.util.subprocess import subprocess


async def docker_create_app(name: str):
	await subprocess('docker-compose', 'create', cwd=get_installed_apps_path() / name)
	with apps_table() as apps:
		apps.update({'status': Status.STOPPED}, Query().name == name)
	await signals.on_apps_update.send_async()


@throttle(5)
async def docker_start_app(name: str):
	await subprocess('docker-compose', 'up', '-d', cwd=get_installed_apps_path() / name)
	with apps_table() as apps:
		apps.update({'status': Status.RUNNING}, Query().name == name)
	await signals.on_apps_update.send_async()


async def docker_stop_app(name: str):
	with apps_table() as apps:
		# todo: think more about how to handle different states
		if apps.get(Query().name == name)['status'] != Status.RUNNING:
			return
	await subprocess('docker-compose', 'stop', cwd=get_installed_apps_path() / name)
	with apps_table() as apps:
		apps.update({'status': Status.STOPPED}, Query().name == name)
	await signals.on_apps_update.send_async()


async def docker_shutdown_app(name: str):
	with apps_table() as apps:
		# todo: think more about how to handle different states
		if apps.get(Query().name == name)['status'] != Status.STOPPED:
			return
	await subprocess('docker-compose', 'down', cwd=get_installed_apps_path() / name)
	with apps_table() as apps:
		apps.update({'status': Status.DOWN}, Query().name == name)
	await signals.on_apps_update.send_async()


async def docker_stop_all_apps():
	apps = get_installed_apps()
	tasks = [docker_stop_app(app) for app in apps]
	await asyncio.gather(*tasks)


async def docker_shutdown_all_apps():
	apps = get_installed_apps()
	tasks = [docker_shutdown_app(app) for app in apps]
	await asyncio.gather(*tasks)


def get_installed_apps_path() -> Path:
	return Path(gconf.get('path_root')) / 'core' / 'installed_apps'


def get_installed_apps() -> Set[str]:
	installed_apps_path = Path(gconf.get('path_root')) / 'core' / 'installed_apps'
	installed_apps_path.mkdir(exist_ok=True, parents=True)
	installed_apps = {p.name for p in installed_apps_path.iterdir()}
	return installed_apps


def get_app_metadata(app_name: str) -> AppMeta:
	app_path = get_installed_apps_path() / app_name
	if not app_path.exists():
		raise NoSuchAppDirectory(app_name)
	with open(app_path / 'app.json') as f:
		return AppMeta(**json.load(f))


class NoSuchAppDirectory(Exception):
	pass
