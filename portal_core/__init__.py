import logging
import os
import sys
from importlib.metadata import metadata
from pathlib import Path

import gconf
import jinja2
from fastapi import FastAPI, Request, Response

from portal_core.database import database, migration
from .database.database import identities_table
from .model.identity import Identity
from .service import app_store, init_apps, app_infra, identity, app_lifecycle
from .service.peer import update_all_peer_pubkeys
from .service.signed_call import signed_request
from .util.background_task import BackgroundTaskHandler
from .web import internal, public, protected

log = logging.getLogger(__name__)


def create_app():
	shipped_config = gconf.load('config.yml')
	additional_config = gconf.load(os.environ['CONFIG']) if 'CONFIG' in os.environ else None
	configure_logging()
	log.debug(f'loaded shipped config {shipped_config}')
	if additional_config:
		log.debug(f'loaded additional config {additional_config}')

	database.init_database()
	migration.migrate_all()

	default_identity = identity.init_default_identity()
	_ensure_traefik_config(default_identity)

	app_store.refresh_app_store()
	init_apps.refresh_init_apps()
	log.debug('refreshed initial apps')

	app_infra.refresh_app_infra()
	log.debug('written app infra files (docker-compose and traefik)')

	bg_tasks = BackgroundTaskHandler([
		(app_lifecycle.stop_apps, gconf.get('apps.lifecycle.refresh_interval')),
		(update_all_peer_pubkeys, 60),
	])
	bg_tasks.start()

	app_meta = metadata('portal_core')
	app = FastAPI(
		title='Portal Core',
		description=app_meta['summary'],
		version=app_meta['version'],
		redoc_url='/redoc',
	)
	app.include_router(internal.router)
	app.include_router(public.router)
	app.include_router(protected.router)

	if gconf.get('log.requests', default=False):
		@app.middleware('http')
		async def log_http(request: Request, call_next):
			response: Response = await call_next(request)
			await _log_request_and_response(request, response)
			return response

	@app.on_event('shutdown')
	def shutdown_event():
		bg_tasks.stop().wait()

	return app


def configure_logging():
	logging.basicConfig(
		format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
		handlers=[logging.StreamHandler(sys.stdout)])
	for module, level in gconf.get('log.levels').items():  # type: str, str
		logger = logging.getLogger() if module == 'root' else logging.getLogger(module)
		logger.setLevel(getattr(logging, level.upper()))


def _ensure_traefik_config(id_: Identity):
	source = Path('/core/traefik.template.yml')
	target = Path('/core/traefik.yml')
	if target.exists():
		if target.is_dir():
			log.info('traefik.yml is a directory, deleting it')
			target.rmdir()
		else:
			log.info('traefik.yml already exists, not touching it')
			return

	if not source.exists():
		log.error(f'{source} not found')
		return

	prefix_length = gconf.get('dns.prefix length')

	template = jinja2.Template(
		source.read_text(),
		variable_start_string='%%',
		variable_end_string='%%',
	)
	with open(target, 'w') as f_traefik:
		f_traefik.write(template.render(identity=id_.id[:prefix_length]))

	log.info('created traefik config')


async def _log_request_and_response(request: Request, response: Response):
	entry = [
		'### HTTP ###',
		'>' * 10,
		f'{request.method} {request.url}',
		'-' * 10,
		*[f'{k}: {v}' for k, v in request.headers.items()],
		'-' * 10,
		str(await request.body()),
		'=' * 10,
		str(response.status_code),
		*[f'{k}: {v}' for k, v in response.headers.items()],
		'<' * 10,
	]
	log.info('\n'.join(entry))
