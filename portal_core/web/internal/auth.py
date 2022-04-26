import logging

from cachetools import cached, TTLCache
from fastapi import HTTPException, APIRouter, Cookie, Response, status, Header
from jinja2 import Template
from tinydb import Query
from tinydb.table import Table

from portal_core.database.database import apps_table, identities_table
from portal_core.model.app import InstalledApp, Access, Path
from portal_core.model.identity import Identity, SafeIdentity
from portal_core.service import pairing, app_lifecycle

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
	app = _get_app(x_forwarded_host)
	access_path = _determine_access_path(x_forwarded_uri, app)
	auth_header_values = _make_auth_header_values(authorization)
	portal_header_values = _get_portal_identity()

	if access_path.access == Access.PRIVATE and auth_header_values['client_type'] != 'terminal':
		log.debug(f'denied auth for {x_forwarded_host}{x_forwarded_uri} -> no valid auth token')
		raise HTTPException(status.HTTP_401_UNAUTHORIZED)

	if access_path.headers:
		for header_key, header_template in access_path.headers.items():
			response.headers[header_key] = Template(header_template) \
				.render(auth=auth_header_values, portal=portal_header_values)
	log.debug(f'granted auth for {x_forwarded_host}{x_forwarded_uri} with headers {response.headers.items()}')

	app_lifecycle.ensure_app_is_running(app)


def _get_app(x_forwarded_host):
	app_name = x_forwarded_host.split('.')[0]
	app = _find_app(app_name)
	if not app:
		log.debug(f'denied auth for {x_forwarded_host} -> unknown app')
		raise HTTPException(status.HTTP_404_NOT_FOUND)
	return app


@cached(cache=TTLCache(maxsize=8, ttl=3))
def _get_portal_identity():
	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))
	return SafeIdentity.from_identity(default_identity)


@cached(cache=TTLCache(maxsize=32, ttl=3))
def _find_app(app_name):
	with apps_table() as apps:  # type: Table
		app = InstalledApp(**apps.get(Query().name == app_name))
	return app


def _determine_access_path(uri, app: InstalledApp) -> Path:
	for path, props in sorted(app.paths.items(), key=lambda x: len(x[0]), reverse=True):  # type: (str, Path)
		if uri.startswith(path):
			return props


def _make_auth_header_values(authorization):
	header_values = {}
	try:
		terminal = pairing.verify_terminal_jwt(authorization)
	except pairing.InvalidJwt:
		header_values['client_type'] = 'public'
	else:
		header_values['client_type'] = 'terminal'
		header_values['client_id'] = terminal.id
		header_values['client_name'] = terminal.name
	return header_values
