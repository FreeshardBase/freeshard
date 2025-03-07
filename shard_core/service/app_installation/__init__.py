import logging

import gconf

from shard_core.database.database import installed_apps_table
from shard_core.model.app_meta import InstallationReason, InstalledApp, Status
from shard_core.util import signals
from shard_core.util.subprocess import subprocess, SubprocessError
from . import util, worker
from .exceptions import AppAlreadyInstalled, AppDoesNotExist, AppNotInstalled

log = logging.getLogger(__name__)


async def install_app_from_store(
		name: str,
		installation_reason: InstallationReason = InstallationReason.STORE,
):
	if not await util.app_exists_in_store(name):
		raise AppDoesNotExist(name)

	if util.app_exists_in_db(name):
		raise AppAlreadyInstalled(name)

	with installed_apps_table() as installed_apps:
		installed_app = InstalledApp(
			name=name,
			installation_reason=installation_reason,
			status=Status.INSTALLATION_QUEUED,
		)
		installed_apps.insert(installed_app.dict())

	installation_task = worker.InstallationTask(
		app_name=name,
		task_type='install from store',
	)
	worker.installation_worker.enqueue(installation_task)
	signals.on_apps_update.send()
	log.info(f'created {installation_task}')


async def install_app_from_existing_zip(
		name: str,
		installation_reason: InstallationReason = InstallationReason.CUSTOM
):
	if util.app_exists_in_db(name):
		raise AppAlreadyInstalled(name)

	with installed_apps_table() as installed_apps:
		installed_app = InstalledApp(
			name=name,
			installation_reason=installation_reason,
			status=Status.INSTALLATION_QUEUED,
		)
		installed_apps.insert(installed_app.dict())

	installation_task = worker.InstallationTask(
		app_name=name,
		task_type='install from zip',
	)
	worker.installation_worker.enqueue(installation_task)
	signals.on_apps_update.send()
	log.info(f'created {installation_task}')


def uninstall_app(name: str):
	if not util.app_exists_in_db(name):
		raise AppNotInstalled(name)

	util.update_app_status(name, Status.UNINSTALLATION_QUEUED)

	uninstallation_task = worker.InstallationTask(
		app_name=name,
		task_type='uninstall',
	)
	worker.installation_worker.enqueue(uninstallation_task)

	signals.on_apps_update.send()
	log.info(f'created {uninstallation_task}')


async def reinstall_app(name: str):
	if not await util.app_exists_in_store(name):
		raise AppDoesNotExist(name)

	if not util.app_exists_in_db(name):
		raise AppNotInstalled(name)

	util.update_app_status(name, Status.REINSTALLATION_QUEUED)

	reinstallation_task = worker.InstallationTask(
		app_name=name,
		task_type='reinstall',
	)
	worker.installation_worker.enqueue(reinstallation_task)

	log.info(f'created {reinstallation_task}')


async def refresh_init_apps():
	configured_init_apps = set(gconf.get('apps.initial_apps'))
	with installed_apps_table() as apps:
		installed_apps = {app['name'] for app in apps.all()}

	for app_name in configured_init_apps - installed_apps:
		log.info(f'installing initial app {app_name}')
		await install_app_from_store(app_name, InstallationReason.CONFIG)
	log.debug('refreshed initial apps')


async def login_docker_registries():
	registries = gconf.get('apps.registries')
	for r in registries:
		try:
			await subprocess('docker', 'login', '-u', r['username'], '-p', r['password'], r['uri'])
		except SubprocessError as e:
			log.error(f'could not log in to registry {r["uri"]}: {e}')
		else:
			log.debug(f'logged in to registry {r["uri"]}')
