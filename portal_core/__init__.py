import logging
import os
import shutil
import sys
from contextlib import asynccontextmanager
from importlib.metadata import metadata
from pathlib import Path

import gconf
from fastapi import FastAPI, Request, Response

from portal_core.database import database
from .service import app_store, identity, app_lifecycle, peer, app_usage_reporting
from .service.app_tools import docker_stop_all_apps, docker_remove_all_apps
from .util.async_util import Periodic
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

	app_meta = metadata('portal_core')
	app = FastAPI(
		title='Portal Core',
		description=app_meta['summary'],
		version=app_meta['version'],
		redoc_url='/redoc',
		lifespan=lifespan,
	)
	app.include_router(internal.router)
	app.include_router(public.router)
	app.include_router(protected.router)
	app.include_router(management.router)

	if gconf.get('log.requests', default=False):
		@app.middleware('http')
		async def log_http(request: Request, call_next):
			response: Response = await call_next(request)
			await _log_request_and_response(request, response)
			return response

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
	await app_store.login_docker_registries()

	await app_store.refresh_init_apps()
	log.debug('refreshed initial apps')

	background_tasks = [
		Periodic(
			app_lifecycle.control_apps,
			delay=gconf.get('apps.lifecycle.refresh_interval')),
		Periodic(
			peer.update_all_peer_pubkeys, delay=60),
		Periodic(
			app_usage_reporting.track_currently_installed_apps,
			cron=gconf.get('apps.usage_reporting.tracking_schedule')),
		Periodic(
			app_usage_reporting.report_app_usage,
			cron=gconf.get('apps.usage_reporting.reporting_schedule')),
	]
	for t in background_tasks:
		t.start()

	yield  # === run app ===

	for t in background_tasks:
		t.stop()
	for t in background_tasks:
		await t.wait()
	await docker_stop_all_apps()
	await docker_remove_all_apps()


def _copy_traefik_static_config():
	source = Path.cwd() / 'data' / 'traefik.yml'
	root = Path(gconf.get('path_root'))
	target = root / 'core' / 'traefik.yml'
	shutil.copy(source, target)


async def _log_request_and_response(request: Request, response: Response):
	entry = [
		'### HTTP ###',
		'>' * 10,
		f'{request.method} {request.url}',
		'-' * 10,
		*[f'{k}: {v}' for k, v in request.headers.items()],
		'=' * 10,
		str(response.status_code),
		*[f'{k}: {v}' for k, v in response.headers.items()],
		'<' * 10,
	]
	log.info('\n'.join(entry))
