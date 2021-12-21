import logging
import sys
from importlib.metadata import metadata
from pathlib import Path

import gconf
import jinja2
from fastapi import FastAPI

from . import database
from .database import get_db
from .model.identity import Identity
from .service import app_store, init_apps, compose, identity
from .web import public, protected

log = logging.getLogger(__name__)


def create_app():
	loaded_config = gconf.load('config.yml')
	configure_logging()
	log.debug(f'loaded config {loaded_config}')

	database.init_database()
	log.debug('Initialized DB')

	default_identity = identity.init_default_identity()
	_ensure_traefik_config(default_identity)

	app_store.refresh_app_store()

	init_apps.refresh_init_apps()
	log.debug('refreshed initial apps')

	compose.refresh_docker_compose()
	log.debug('launched docker-compose')

	app_meta = metadata('portal_core')
	app = FastAPI(
		title='Portal Core',
		description=app_meta['summary'],
		version=app_meta['version'],
		redoc_url='/redoc',
	)
	app.include_router(public.router)
	app.include_router(protected.router)

	return app


def configure_logging():
	logging.basicConfig(
		format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
		handlers=[logging.StreamHandler(sys.stdout)])
	for module, level in gconf.get('log').items():  # type: str, str
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
