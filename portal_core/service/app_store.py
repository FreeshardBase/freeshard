import json
import logging
import datetime
import threading
from pathlib import Path

import jinja2
import pydantic
import yaml

from azure.storage.blob.aio import ContainerClient
from typing import Optional

import gconf
from pydantic import BaseModel
from tinydb import Query

from portal_core.database.database import apps_table, identities_table
from portal_core.model.app_meta import AppMeta, InstalledApp, InstallationReason, Status
from portal_core.service.app_tools import docker_create_app, get_installed_apps_path, get_installed_apps, \
	get_app_metadata
from portal_core.service.traefik_dynamic_config import compile_config, AppInfo
from portal_core.model.identity import SafeIdentity, Identity

log = logging.getLogger(__name__)

install_lock = threading.RLock()


class AppStoreStatus(BaseModel):
	current_branch: str
	commit_id: str
	last_update: Optional[datetime.datetime]


async def install_store_app(
		name: str,
		installation_reason: InstallationReason = InstallationReason.STORE,
		store_branch: Optional[str] = 'feature-docker-compose',  # todo: change back to master
):
	with apps_table() as apps:  # type: Table
		if apps.contains(Query().name == name):
			raise AppAlreadyInstalled(name)
		installed_app = InstalledApp(
			name=name,
			installation_reason=installation_reason,
			status=Status.INSTALLING,
			from_branch=store_branch,
		)
		apps.insert(installed_app.dict())

	with install_lock:
		await download_azure_blob_directory(
			f'{store_branch}/all_apps/{name}',
			get_installed_apps_path() / name,
		)
		write_traefik_dyn_config()
		await render_docker_compose_template(installed_app)
		await docker_create_app(name)


class AppAlreadyInstalled(Exception):
	pass


async def download_azure_blob_directory(directory_name: str, target_dir: Path):
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


async def render_docker_compose_template(app: InstalledApp):
	fs = {
		'app_data': Path(gconf.get('path_root')) / 'user_data' / 'app_data' / app.name,
		'shared_documents': Path(gconf.get('path_root')) / 'user_data' / 'shared' / 'documents',
		'shared_media': Path(gconf.get('path_root')) / 'user_data' / 'shared' / 'media',
		'shared_music': Path(gconf.get('path_root')) / 'user_data' / 'shared' / 'music',
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
	installed_apps = get_installed_apps()

	for app_name in configured_init_apps - installed_apps:
		await install_store_app(app_name, InstallationReason.CONFIG)


def write_traefik_dyn_config():
	with apps_table() as apps:
		apps = [InstalledApp(**a) for a in apps.all()]
	app_infos = [AppInfo(get_app_metadata(a.name), installed_app=a) for a in apps]

	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))  # noqa: E712
	portal = SafeIdentity.from_identity(default_identity)

	traefik_dyn_filename = Path(gconf.get('path_root')) / 'core' / 'traefik_dyn' / 'traefik_dyn.yml'
	write_to_yaml(compile_config(app_infos, portal), traefik_dyn_filename)


def write_to_yaml(spec: pydantic.BaseModel, output_path: Path):
	output_path.parent.mkdir(exist_ok=True, parents=True)
	with open(output_path, 'w') as f:
		f.write('# == DO NOT MODIFY ==\n# this file is auto-generated\n\n')
		f.write(yaml.dump(spec.dict(exclude_none=True)))
