import logging

from cachetools import cached, TTLCache
from fastapi import HTTPException, APIRouter, Cookie, Response, status, Header
from jinja2 import Template
from tinydb import Query
from tinydb.table import Table

from portal_core.database.database import apps_table
from portal_core.model.app import InstalledApp, Access
from portal_core.model.app import Path
from portal_core.service import pairing

log = logging.getLogger(__name__)

router = APIRouter()


@router.get('/authenticate_terminal', status_code=status.HTTP_200_OK)
def authenticate_terminal(response: Response, authorization: str = Cookie(None)):
	if not authorization:
		raise HTTPException(status.HTTP_401_UNAUTHORIZED)

	try:
		terminal = pairing.verify_terminal_jwt(authorization)
	except pairing.InvalidJwt:
		raise HTTPException(status.HTTP_401_UNAUTHORIZED)
	else:
		response.headers['X-Ptl-Client-Type'] = 'terminal'
		response.headers['X-Ptl-Client-Id'] = terminal.id
		response.headers['X-Ptl-Client-Name'] = terminal.name


@router.get('/auth', status_code=status.HTTP_200_OK)
def authenticate_and_authorize(
		response: Response,
		authorization: str = Cookie(None),
		x_forwarded_host: str = Header(None),
		x_forwarded_uri: str = Header(None),
):
	app_name = x_forwarded_host.split('.')[0]
	app = get_app(app_name)
	if not app:
		log.debug(f'denied auth for {x_forwarded_host}{x_forwarded_uri} -> unknown app')
		raise HTTPException(status.HTTP_404_NOT_FOUND)
	access = _determine_access(x_forwarded_uri, app)
	header_template_values = {}

	if access.access == Access.PRIVATE:
		if not authorization:
			log.debug(f'denied auth for {x_forwarded_host}{x_forwarded_uri} -> no auth token')
			raise HTTPException(status.HTTP_401_UNAUTHORIZED)
		try:
			terminal = pairing.verify_terminal_jwt(authorization)
			header_template_values['client_id'] = terminal.id
			header_template_values['client_name'] = terminal.name
		except pairing.InvalidJwt:
			log.debug(f'denied auth for {x_forwarded_host}{x_forwarded_uri} -> invalid auth token')
			raise HTTPException(status.HTTP_401_UNAUTHORIZED)

	if access.headers:
		for header_key, header_template in access.headers.items():
			response.headers[header_key] = Template(header_template).render(header_template_values)
	log.debug(f'granted auth for {x_forwarded_host}{x_forwarded_uri} with headers {response.headers.items()}')


@cached(cache=TTLCache(maxsize=32, ttl=3))
def get_app(app_name):
	with apps_table() as apps:  # type: Table
		app = InstalledApp(**apps.get(Query().name == app_name))
	return app


def _determine_access(uri, app: InstalledApp) -> Path:
	for path, props in sorted(app.paths.items(), key=lambda x: len(x[0]), reverse=True):  # type: (str, Path)
		if uri.startswith(path):
			return props
