import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Set

import gconf
from tinydb import Query

from portal_core.database.database import apps_table
from portal_core.model.app_meta import Status, AppMeta
from portal_core.util.subprocess import subprocess


async def docker_create_app(name: str):
	await subprocess('docker-compose', 'create', cwd=get_installed_apps_path() / name)
	with apps_table() as apps:
		apps.update({'status': Status.STOPPED}, Query().name == name)


async def docker_start_app(name: str):
	await subprocess('docker-compose', 'up', '-d', cwd=get_installed_apps_path() / name)
	with apps_table() as apps:
		apps.update({'status': Status.RUNNING}, Query().name == name)


async def docker_stop_app(name: str):
	await subprocess('docker-compose', 'stop', cwd=get_installed_apps_path() / name)
	with apps_table() as apps:
		apps.update({'status': Status.STOPPED}, Query().name == name)


async def docker_remove_app(name: str):
	await subprocess('docker-compose', 'down', cwd=get_installed_apps_path() / name)
	with apps_table() as apps:
		apps.update({'status': Status.ABSENT}, Query().name == name)


async def docker_stop_all_apps():
	apps = get_installed_apps()
	tasks = [docker_stop_app(app) for app in apps]
	await asyncio.gather(*tasks)


async def docker_remove_all_apps():
	apps = get_installed_apps()
	tasks = [docker_remove_app(app) for app in apps]
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
		raise AppNotInstalled(app_name)
	with open(app_path / 'app.json') as f:
		return AppMeta(**json.load(f))


@asynccontextmanager
async def docker_network_portal():
	await subprocess('docker', 'network', 'create', 'portal')
	try:
		yield
	finally:
		await subprocess('docker', 'network', 'rm', 'portal')


class AppNotInstalled(Exception):
	pass
