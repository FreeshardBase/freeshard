import logging
import sys
from importlib.metadata import metadata

import gconf
from fastapi import FastAPI

from . import database
from .service import app_store, init_apps, compose
from .web import public, protected

log = logging.getLogger(__name__)


def create_app():
	loaded_config = gconf.load('config.yml')
	configure_logging()
	log.debug(f'loaded config {loaded_config}')

	database.init_database()
	log.debug('Initialized DB')

	app_store.refresh_app_store()

	init_apps.refresh_init_apps()
	log.debug('refreshed initial apps')

	compose.refresh_docker_compose()
	log.debug('launched docker-compose')

	app_meta = metadata('app_controller')
	app = FastAPI(
		title='App Controller',
		description=app_meta['summary'],
		version=app_meta['version'],
		redoc_url='/',
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
