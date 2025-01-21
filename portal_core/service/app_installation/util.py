import logging
from pathlib import Path

import aiofiles
import gconf
import httpx
import jinja2
import pydantic
import yaml
from tinydb import Query

from portal_core.database.database import installed_apps_table, identities_table
from portal_core.model.app_meta import Status, InstalledApp
from portal_core.model.identity import Identity, SafeIdentity
from portal_core.service.app_installation.exceptions import AppInIllegalStatus
from portal_core.service.app_tools import get_installed_apps_path, get_app_metadata
from portal_core.service.traefik_dynamic_config import AppInfo, compile_config
from portal_core.util import signals

log = logging.getLogger(__name__)


def get_app_from_db(app_name: str) -> InstalledApp:
	with installed_apps_table() as installed_apps:
		if record := installed_apps.get(Query().name == app_name):
			return InstalledApp.parse_obj(record)
		else:
			raise KeyError(app_name)


def app_exists_in_db(app_name: str) -> bool:
	with installed_apps_table() as installed_apps:
		return installed_apps.contains(Query().name == app_name)


def assert_app_status(installed_app: InstalledApp, *allowed_status: Status):
	if installed_app.status not in allowed_status:
		raise AppInIllegalStatus(
			f'App {installed_app.name} is in status {installed_app.status}, should be one of {allowed_status}')


def update_app_status(app_name: str, status: Status, message: str | None = None):
	with installed_apps_table() as installed_apps:
		updated_docs = installed_apps.update({'status': status}, Query().name == app_name)
	if len(updated_docs) == 0:
		raise KeyError(app_name)
	log.debug(f'status of {app_name} updated to {status}' + (f': {message}' if message else ''))
	signals.on_apps_update.send()


async def app_exists_in_store(name: str) -> bool:
	app_store = gconf.get('apps.app_store')
	url = f'{app_store["base_url"]}/{app_store["container_name"]}/master/all_apps/{name}/{name}.zip'
	async with httpx.AsyncClient() as client:
		response = await client.get(url)
		return response.status_code == 200


async def render_docker_compose_template(app: InstalledApp):
	log.debug(f'creating docker-compose.yml for app {app.name}')
	fs = {
		'app_data': f'{gconf.get("path_root_host")}/user_data/app_data/{app.name}',
		'all_app_data': f'{gconf.get("path_root_host")}/user_data/app_data',
		'shared': f'{gconf.get("path_root_host")}/user_data/shared',
	}

	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))  # noqa: E712
	portal = SafeIdentity.from_identity(default_identity)

	app_dir = get_installed_apps_path() / app.name
	template = jinja2.Template((app_dir / 'docker-compose.yml.template').read_text())
	(app_dir / 'docker-compose.yml').write_text(template.render(
		fs=fs, portal=portal,
	))


async def write_traefik_dyn_config():
	log.debug('updating traefik dynamic config')
	with installed_apps_table() as installed_apps:
		installed_apps = [InstalledApp(**a) for a in installed_apps.all() if a['status'] != Status.INSTALLATION_QUEUED]
	app_infos = [AppInfo(get_app_metadata(a.name), installed_app=a) for a in installed_apps if a.status != Status.ERROR]

	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))  # noqa: E712
	portal = SafeIdentity.from_identity(default_identity)

	traefik_dyn_filename = Path(gconf.get('path_root')) / 'core' / 'traefik_dyn' / 'traefik_dyn.yml'
	await _write_to_yaml(compile_config(app_infos, portal), traefik_dyn_filename)


async def _write_to_yaml(spec: pydantic.BaseModel, output_path: Path):
	output_path.parent.mkdir(exist_ok=True, parents=True)
	async with aiofiles.open(output_path, 'w') as f:
		await f.write('# == DO NOT MODIFY ==\n# this file is auto-generated\n\n')
		await f.write(yaml.dump(spec.dict(exclude_none=True)))
