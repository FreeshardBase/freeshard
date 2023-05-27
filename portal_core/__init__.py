import logging
import os
import sys
from contextlib import asynccontextmanager
from importlib.metadata import metadata
from pathlib import Path

import gconf
import jinja2
from fastapi import FastAPI, Request, Response

from portal_core.database import database, migration
from .model.identity import Identity
from .service import app_store, identity, app_lifecycle, peer, app_usage_reporting
from .service.app_lifecycle import stop_all_apps, remove_all_apps
from .util.async_util import Periodic
from .web import internal, public, protected, management

log = logging.getLogger(__name__)


async def create_app():
	shipped_config = gconf.load('config.yml')
	additional_config = gconf.load(os.environ['CONFIG']) if 'CONFIG' in os.environ else None
	configure_logging()
	log.info(f'loaded shipped config {str(shipped_config)}')
	if additional_config:
		log.info(f'loaded additional config {str(additional_config)}')

	database.init_database()
	migration.migrate_all()

	default_identity = identity.init_default_identity()
	try:
		_render_traefik_static_config(default_identity)
	except FileNotFoundError:
		log.error('Traefik template not found, Traefik config cannot be created')

	await app_store.refresh_init_apps()
	log.debug('refreshed initial apps')

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
	yield
	await stop_all_apps()
	await remove_all_apps()
	for t in background_tasks:
		t.stop()
	for t in background_tasks:
		await t.wait()


def _render_traefik_static_config(id_: Identity):
	root = Path(gconf.get('path_root'))
	source = root / 'core/traefik.template.yml'
	target = root / 'core/traefik.yml'
	if target.exists() and target.is_dir():
		log.info('traefik.yml is a directory, deleting it')
		target.rmdir()

	if not source.exists():
		raise FileNotFoundError(source.absolute())

	gconf.get('dns.prefix length')

	template = jinja2.Template(
		source.read_text(),
		variable_start_string='%%',
		variable_end_string='%%',
	)
	with open(target, 'w') as f_traefik:
		f_traefik.write(template.render(identity=id_.short_id))

	log.info('created traefik static config')


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
