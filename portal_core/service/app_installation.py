import asyncio
import datetime
import logging
import shutil
from contextlib import suppress
from pathlib import Path
from typing import Optional, Dict

import gconf
import jinja2
import pydantic
import yaml
from azure.storage.blob.aio import ContainerClient
from pydantic import BaseModel
from tinydb import Query

from portal_core.database.database import installed_apps_table, identities_table
from portal_core.model.app_meta import InstalledApp, InstallationReason, Status
from portal_core.model.identity import SafeIdentity, Identity
from portal_core.service.app_tools import docker_create_app, get_installed_apps_path, get_app_metadata, \
	docker_shutdown_app, docker_stop_app
from portal_core.service.traefik_dynamic_config import compile_config, AppInfo
from portal_core.util import signals
from portal_core.util.subprocess import subprocess

log = logging.getLogger(__name__)

install_lock = asyncio.Lock()
installation_tasks: Dict[str, asyncio.Task] = {}


class AppStoreStatus(BaseModel):
	current_branch: str
	commit_id: str
	last_update: Optional[datetime.datetime]


async def install_store_app(
		name: str,
		installation_reason: InstallationReason = InstallationReason.STORE,
		store_branch: Optional[str] = 'feature-docker-compose',  # todo: change back to master
):
	if not await _app_exists(name, store_branch):
		raise AppDoesNotExist(name)

	with installed_apps_table() as installed_apps:
		if installed_apps.contains(Query().name == name):
			raise AppAlreadyInstalled(name)

		installed_app = InstalledApp(
			name=name,
			installation_reason=installation_reason,
			status=Status.INSTALLATION_QUEUED,
			from_branch=store_branch,
		)
		installed_apps.insert(installed_app.dict())

	task = asyncio.create_task(_install_app_task(installed_app))
	installation_tasks[name] = task
	await signals.on_apps_update.send_async()
	log.info(f'created installation task for {name}')
	log.debug(f'installation tasks: {installation_tasks.keys()}')


async def _install_app_task(installed_app: InstalledApp):
	async with install_lock:
		log.info(f'starting installation of {installed_app.name}')
		with installed_apps_table() as installed_apps:
			installed_apps.update({'status': Status.INSTALLING}, Query().name == installed_app.name)
		await signals.on_apps_update.send_async()
		try:
			log.debug(f'downloading app {installed_app.name} from store')
			await _download_azure_blob_directory(
				f'{installed_app.from_branch}/all_apps/{installed_app.name}',
				get_installed_apps_path() / installed_app.name,
			)
			log.debug('updating traefik dynamic config')
			_write_traefik_dyn_config()
			log.debug(f'creating docker-compose.yml for app {installed_app.name}')
			await _render_docker_compose_template(installed_app)
			log.debug(f'creating containers for app {installed_app.name}')
			await docker_create_app(installed_app.name)
			log.info(f'finished installation of {installed_app.name}')
		except Exception as e:
			log.error(f'Error while installing app {installed_app.name}: {e!r}')
			with installed_apps_table() as installed_apps:
				installed_apps.update({'status': Status.ERROR}, Query().name == installed_app.name)
			await signals.on_apps_update.send_async()
			await signals.on_app_install_error.send_async(e, name=installed_app.name)
		finally:
			del installation_tasks[installed_app.name]


async def cancel_all_installations(wait=False):
	for name in list(installation_tasks.keys()):
		await cancel_installation(name)
	if wait:
		for task in list(installation_tasks.values()):
			with suppress(asyncio.CancelledError):
				await task


async def cancel_installation(name: str):
	if name not in installation_tasks:
		raise AppNotInstalled(name)
	installation_tasks[name].cancel()
	with installed_apps_table() as installed_apps:
		installed_apps.update({'status': Status.ERROR}, Query().name == name)
	await signals.on_apps_update.send_async()
	log.debug(f'cancelled installation of {name}')


async def uninstall_app(name: str):
	log.info(f'starting uninstallation of {name}')
	with installed_apps_table() as installed_apps:
		if not installed_apps.contains(Query().name == name):
			raise AppNotInstalled(name)
		installed_apps.update({'status': Status.UNINSTALLING}, Query().name == name)
	await signals.on_apps_update.send_async()

	async with install_lock:
		log.debug(f'shutting down docker container for app {name}')
		await docker_stop_app(name, set_status=False)
		await docker_shutdown_app(name, set_status=False)

		log.debug(f'deleting app data for {name}')
		shutil.rmtree(Path(get_installed_apps_path() / name))
		log.debug(f'removing app {name} from database')
		with installed_apps_table() as installed_apps:
			installed_apps.remove(Query().name == name)
		log.debug('updating traefik dynamic config')
		_write_traefik_dyn_config()
		await signals.on_apps_update.send_async()
		log.debug(f'finished uninstallation of {name}')


class AppAlreadyInstalled(Exception):
	pass


class AppDoesNotExist(Exception):
	pass


class AppNotInstalled(Exception):
	pass


async def _app_exists(name: str, branch: str = 'feature-docker-compose') -> bool:
	async with ContainerClient(
			account_url=gconf.get('apps.app_store.base_url'),
			container_name=gconf.get('apps.app_store.container_name'),
	) as container_client:
		directory_name = f'{branch}/all_apps/{name}/'
		pages = container_client.list_blob_names(name_starts_with=directory_name)
		async for page in pages.by_page():
			async for _ in page:
				return True
		return False


async def _download_azure_blob_directory(directory_name: str, target_dir: Path):
	async with ContainerClient(
			account_url=gconf.get('apps.app_store.base_url'),
			container_name=gconf.get('apps.app_store.container_name'),
	) as container_client:

		directory_name = directory_name.rstrip('/')
		async for blob in container_client.list_blobs(name_starts_with=directory_name):
			if blob.name.endswith('/'):
				continue
			target_file = target_dir / blob.name[len(directory_name) + 1:]
			target_file.parent.mkdir(exist_ok=True, parents=True)
			with open(target_file, 'wb') as f:
				download_blob = await container_client.download_blob(blob)
				f.write(await download_blob.readall())


async def _render_docker_compose_template(app: InstalledApp):
	fs = {
		'app_data': f'/home/portal/user_data/app_data/{app.name}',
		'all_app_data': '/home/portal/user_data/app_data',
		'shared': '/home/portal/user_data/shared',
	}

	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))  # noqa: E712
	portal = SafeIdentity.from_identity(default_identity)

	app_dir = get_installed_apps_path() / app.name
	template = jinja2.Template((app_dir / 'docker-compose.yml.template').read_text())
	(app_dir / 'docker-compose.yml').write_text(template.render(
		fs=fs, portal=portal,
	))


async def refresh_init_apps():
	configured_init_apps = set(gconf.get('apps.initial_apps'))
	with installed_apps_table() as apps:
		installed_apps = {app['name'] for app in apps.all()}

	for app_name in configured_init_apps - installed_apps:
		await install_store_app(app_name, InstallationReason.CONFIG)


def _write_traefik_dyn_config():
	with installed_apps_table() as installed_apps:
		installed_apps = [InstalledApp(**a) for a in installed_apps.all() if a['status'] != Status.INSTALLATION_QUEUED]
	app_infos = [AppInfo(get_app_metadata(a.name), installed_app=a) for a in installed_apps]

	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))  # noqa: E712
	portal = SafeIdentity.from_identity(default_identity)

	traefik_dyn_filename = Path(gconf.get('path_root')) / 'core' / 'traefik_dyn' / 'traefik_dyn.yml'
	_write_to_yaml(compile_config(app_infos, portal), traefik_dyn_filename)


def _write_to_yaml(spec: pydantic.BaseModel, output_path: Path):
	output_path.parent.mkdir(exist_ok=True, parents=True)
	with open(output_path, 'w') as f:
		f.write('# == DO NOT MODIFY ==\n# this file is auto-generated\n\n')
		f.write(yaml.dump(spec.dict(exclude_none=True)))


async def login_docker_registries():
	registries = gconf.get('apps.registries')
	for r in registries:
		await subprocess('docker', 'login', '-u', r['username'], '-p', r['password'], r['uri'])
		log.debug(f'logged in to registry {r["uri"]}')
