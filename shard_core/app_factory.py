import logging
import os
import sys
from contextlib import asynccontextmanager
from importlib.metadata import metadata
from pathlib import Path
from typing import List

import gconf
import jinja2
from fastapi import FastAPI
from requests import ConnectionError, HTTPError

from .database import database
from .service import app_installation, identity, app_lifecycle, peer, \
	app_usage_reporting, websocket, migration, portal_controller, backup, disk
from .service.app_installation.util import write_traefik_dyn_config
from .service.app_tools import docker_stop_all_apps, docker_shutdown_all_apps, docker_prune_images
from .service.backup import start_backup
from .util.async_util import PeriodicTask, BackgroundTask, CronTask
from .web import internal, public, protected, management

log = logging.getLogger(__name__)


def create_app():
	if 'CONFIG' in os.environ:
		for c in os.environ['CONFIG'].split(','):
			gconf.load(c)
	else:
		gconf.load('config.yml')
	configure_logging()

	database.init_database()
	identity.init_default_identity()
	_copy_traefik_static_config()

	app_meta = metadata('shard_core')
	app = FastAPI(
		title='Shard Core',
		description=app_meta['summary'],
		version=app_meta['version'],
		redoc_url='/redoc',
		lifespan=lifespan,
	)
	app.include_router(internal.router)
	app.include_router(public.router)
	app.include_router(protected.router)
	app.include_router(management.router)

	return app


def configure_logging():
	logging.basicConfig(
		format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
		handlers=[logging.StreamHandler(sys.stdout)])
	for module, level in gconf.get('log.levels').items():  # type: str, str
		logger = logging.getLogger() if module == 'root' else logging.getLogger(module)
		logger.setLevel(getattr(logging, level.upper()))
		log.info(f'set logger for {module} to {level.upper()}')


@asynccontextmanager
async def lifespan(_):
	await write_traefik_dyn_config()
	await app_installation.login_docker_registries()
	await migration.migrate()
	await app_installation.refresh_init_apps()
	backup.ensure_backup_passphrase()
	try:
		await portal_controller.refresh_profile()
	except (ConnectionError, HTTPError) as e:
		log.error(f'could not refresh profile: {e}')

	background_tasks = make_background_tasks()
	for t in background_tasks:
		t.start()

	log.info('Startup complete')
	print_welcome_log()
	yield  # === run app ===
	log.info('Shutting down')

	for t in background_tasks:
		t.stop()
	for t in background_tasks:
		await t.wait()
	await docker_stop_all_apps()
	await docker_shutdown_all_apps(force=True)


def make_background_tasks() -> List[BackgroundTask]:
	return [
		app_installation.worker.installation_worker,
		PeriodicTask(
			app_lifecycle.control_apps, gconf.get('apps.lifecycle.refresh_interval')
		),
		PeriodicTask(peer.update_all_peer_pubkeys, 60),
		CronTask(
			app_usage_reporting.track_currently_installed_apps,
			gconf.get('apps.usage_reporting.tracking_schedule'),
		),
		CronTask(
			app_usage_reporting.report_app_usage,
			gconf.get('apps.usage_reporting.reporting_schedule'),
		),
		CronTask(
			docker_prune_images,
			gconf.get('apps.pruning.schedule'),
		),
		CronTask(
			start_backup,
			cron=gconf.get('services.backup.timing.base_schedule'),
			max_random_delay=gconf.get('services.backup.timing.max_random_delay'),
		),
		PeriodicTask(disk.update_disk_space, 3),
		websocket.ws_worker,
	]


def _copy_traefik_static_config():
	traefik_yml = 'traefik_no_ssl.yml' if gconf.get('traefik.disable_ssl', default=False) else 'traefik.yml'
	source = Path.cwd() / 'data' / traefik_yml
	with open(source, 'r') as f:
		template = jinja2.Template(f.read())

	result = template.render({'acme_email': gconf.get('traefik.acme_email')})

	root = Path(gconf.get('path_root'))
	target = root / 'core' / 'traefik.yml'
	with open(target, 'w') as f:
		f.write(result)


def print_welcome_log():
	i = identity.get_default_identity()
	protocol = 'http' if gconf.get('traefik.disable_ssl', default=False) else 'https'

	with open(Path.cwd() / 'data' / 'freeshard_ascii', 'r') as f:
		welcome_log_template = jinja2.Template(f.read())

	welcome_log = welcome_log_template.render({
		'shard_id': i.short_id,
		'shard_url': f'{protocol}://{i.domain}',
	})

	print(welcome_log)
