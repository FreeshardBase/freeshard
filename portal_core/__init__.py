import logging
import sys
from importlib.metadata import metadata
from pathlib import Path

import gconf
import jinja2
from fastapi import FastAPI, Request, Response

from portal_core.database import database, migration
from .model.identity import Identity
from .service import app_store, init_apps, app_infra, identity, app_lifecycle
from .util.background_task import BackgroundTaskHandler
from .web import internal, public, protected

log = logging.getLogger(__name__)


def create_app():
	shipped_config = gconf.load('config.yml')
	additional_config = gconf.load('core/portal_core_config.yml', required=False)
	configure_logging()
	log.debug(f'loaded shipped config {shipped_config}')
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

	bg_tasks = BackgroundTaskHandler([(app_lifecycle.stop_apps, gconf.get('apps.lifecycle.refresh_interval'))])
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
		async def log_request(request: Request, call_next):
			print('>' * 10)
			await _log_request(request)
			response: Response = await call_next(request)
			print('=' * 10)
			await _log_response(response)
			print('<' * 10)
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


async def _log_request(r: Request):
	print(f'{r.method} {r.url}')
	print('-' * 10)
	for k, v in r.headers.items():
		print(f'{k}: {v}')
	print('-' * 10)
	print(await r.body())


async def _log_response(r: Response):
	print(r.status_code)
	for k, v in r.headers.items():
		print(f'{k}: {v}')
