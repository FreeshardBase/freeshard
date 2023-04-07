import logging

import gconf
from cachetools import cached, TTLCache
from fastapi import HTTPException, APIRouter, Cookie, Response, status, Header, Request
from http_message_signatures import InvalidSignature
from jinja2 import Template
from tinydb import Query

from portal_core.database.database import apps_table, identities_table
from portal_core.model.app import InstalledApp, Access, Path
from portal_core.model.identity import Identity, SafeIdentity
from portal_core.service import pairing, peer as peer_service
from portal_core.util.signals import on_terminal_auth, on_request_to_app, on_peer_auth
from portal_core.model.auth import AuthState


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
		on_terminal_auth.send(terminal)


@router.get('/auth', status_code=status.HTTP_200_OK)
async def authenticate_and_authorize(
		request: Request,
		response: Response,
		authorization: str = Cookie(None),
		x_forwarded_host: str = Header(None),
		x_forwarded_uri: str = Header(None),
):
	app = _match_app(x_forwarded_host)
	path_object = _match_path(x_forwarded_uri, app)
	auth_state = await _get_auth_state(request, authorization)
	log.debug(f'Auth state is {auth_state}')
	portal_header_values = _get_portal_identity()

	if path_object.access == Access.PRIVATE and auth_state.type != AuthState.ClientType.TERMINAL:
		log.debug(f'denied terminal auth for {x_forwarded_host}{x_forwarded_uri}')
		raise HTTPException(status.HTTP_401_UNAUTHORIZED)

	if path_object.access == Access.PEER and auth_state.type != AuthState.ClientType.PEER:
		log.debug(f'denied peer auth for {x_forwarded_host}{x_forwarded_uri}')
		raise HTTPException(status.HTTP_401_UNAUTHORIZED)

	if path_object.headers:
		for header_key, header_template in path_object.headers.items():
			response.headers[header_key] = Template(header_template) \
				.render(auth=auth_state.header_values, portal=portal_header_values)
	log.debug(f'granted auth for {x_forwarded_host}{x_forwarded_uri} with headers {response.headers.items()}')

	on_request_to_app.send(app)


def _match_app(x_forwarded_host):
	app_name = x_forwarded_host.split('.')[0]
	app = _find_app(app_name)
	if not app:
		log.debug(f'denied auth for {x_forwarded_host} -> unknown app')
		raise HTTPException(status.HTTP_404_NOT_FOUND)
	return app


@cached(cache=TTLCache(maxsize=8, ttl=gconf.get('tests.cache_ttl', default=3)))
def _get_portal_identity():
	with identities_table() as identities:
		default_identity = Identity(**identities.get(Query().is_default == True))  # noqa: E712
	return SafeIdentity(**default_identity.dict())


@cached(cache=TTLCache(maxsize=32, ttl=gconf.get('tests.cache_ttl', default=3)))
def _find_app(app_name):
	with apps_table() as apps:  # type: Table
		app = InstalledApp(**apps.get(Query().name == app_name))
	return app


def _match_path(uri, app: InstalledApp) -> Path:
	for path, props in sorted(app.paths.items(), key=lambda x: len(x[0]), reverse=True):  # type: (str, Path)
		if uri.startswith(path):
			return props


async def _get_auth_state(request, authorization) -> AuthState:
	try:
		terminal = pairing.verify_terminal_jwt(authorization)
	except pairing.InvalidJwt as e:
		log.debug(f'invalid terminal JWT: {e}')
	else:
		on_terminal_auth.send(terminal)
		return AuthState(
			x_ptl_client_type=AuthState.ClientType.TERMINAL,
			x_ptl_client_id=terminal.id,
			x_ptl_client_name=terminal.name,
		)

	try:
		peer = await peer_service.verify_peer_auth(request)
	except InvalidSignature as e:
		log.debug(f'invalid signature: {e}')
	except KeyError as e:
		log.debug(f'no such peer: {e}')
	else:
		on_peer_auth.send(peer)
		return AuthState(
			x_ptl_client_type=AuthState.ClientType.PEER,
			x_ptl_client_id=peer.id,
			x_ptl_client_name=peer.name,
		)

	return AuthState(
		x_ptl_client_type=AuthState.ClientType.ANONYMOUS,
	)
