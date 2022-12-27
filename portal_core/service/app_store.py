import io
import json
import logging
import shutil
import tarfile
from pathlib import Path
from typing import Iterable

import gconf
from gitlab import Gitlab, GitlabListError
from tinydb import where

from portal_core.database.database import apps_table
from portal_core.model.app import StoreApp, InstallationReason, AppToInstall
from . import app_infra

log = logging.getLogger(__name__)


def get_store_apps() -> Iterable[StoreApp]:
	sync_dir = Path(gconf.get('path_root')) / 'core' / 'appstore'
	for app_dir in sync_dir.iterdir():
		yield get_store_app(app_dir.name)


def get_store_app(name) -> StoreApp:
	sync_dir = Path(gconf.get('path_root')) / 'core' / 'appstore'
	app_dir = sync_dir / name
	if not app_dir.exists():
		raise KeyError(f'no app named {name}')
	with apps_table() as apps:
		is_installed = apps.contains(where('name') == name)
	with open(app_dir / 'app.json') as f:
		app = json.load(f)
		assert (a := app['name']) == (d := app_dir.name), f'app with name {a} in directory with name {d}'
		return StoreApp(is_installed=is_installed, **app)


def install_store_app(name: str):
	app = get_store_app(name)
	with apps_table() as apps:
		apps.insert(AppToInstall(
			**app.dict(),
			installation_reason=InstallationReason.STORE,
		).dict())
	app_infra.refresh_app_infra()


def refresh_app_store(ref: str = None):
	log.debug(f'refreshing app store with ref {ref}')
	fs_sync_dir = Path(gconf.get('path_root')) / 'core' / 'appstore'

	apps_project = Gitlab('https://gitlab.com').projects.get(gconf.get('apps.app_store.project_id'))
	try:
		archive = tarfile.open(fileobj=io.BytesIO(apps_project.repository_archive(sha=ref or 'master')))
	except GitlabListError as e:
		log.error(f'Error during refreshing app store with ref {ref}: {e.error_message}')
		raise AppStoreRefreshError from e

	if fs_sync_dir.exists():
		shutil.rmtree(fs_sync_dir)

	archive_root = Path(archive.getnames()[0])
	archive_apps = archive_root / 'apps'
	for member in archive.getmembers():
		if member.name.startswith(str(archive_apps)) and member.name != str(archive_apps):
			fs_file = fs_sync_dir / Path(member.name).relative_to(archive_apps)
			if member.isdir():
				fs_file.mkdir(exist_ok=True, parents=True)
			else:
				with open(fs_file, 'wb') as f:
					if data := archive.extractfile(member):
						f.write(data.read())


class AppStoreRefreshError(Exception):
	pass
