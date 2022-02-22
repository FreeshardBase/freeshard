import logging
from enum import Enum

from cachetools import cached, TTLCache
from fastapi import HTTPException, APIRouter, Cookie, Response, status, Header
from tinydb import Query
from tinydb.table import Table

from portal_core.database import apps_table
from portal_core.model.app import InstalledApp, DefaultAccess
from portal_core.service import pairing

log = logging.getLogger(__name__)

router = APIRouter()


class Access(str, Enum):
	PRIVATE = 'private'
	PUBLIC = 'public'
	PEER = 'peer'


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
	log.debug(f'auth attempt for host {x_forwarded_host}, uri {x_forwarded_uri}')
	app_name = x_forwarded_host.split('.')[0]
	app = get_app(app_name)
	if not app:
		raise HTTPException(status.HTTP_404_NOT_FOUND)
	access = _determine_access(x_forwarded_uri, app)

	if access == Access.PUBLIC:
		response.headers['X-Ptl-Client-Type'] = 'public'
		response.headers['X-Ptl-Client-Id'] = ''
		response.headers['X-Ptl-Client-Name'] = ''
	elif access == Access.PRIVATE:
		return authenticate_terminal(response, authorization)
	elif access == Access.PEER:
		raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED)
	else:
		raise NotImplemented(f'invalid access type: {access}')


@cached(cache=TTLCache(maxsize=32, ttl=3))
def get_app(app_name):
	with apps_table() as apps:  # type: Table
		app = InstalledApp(**apps.get(Query().name == app_name))
	return app


def _determine_access(uri, app: InstalledApp) -> Access:
	try:
		app.authentication
	except AttributeError:
		return Access.PRIVATE
	for private_path in app.authentication.private_paths or []:
		if uri.startswith(private_path):
			return Access.PRIVATE
	for public_path in app.authentication.public_paths or []:
		if uri.startswith(public_path):
			return Access.PUBLIC
	for peer_path in app.authentication.peer_paths or []:
		if uri.startswith(peer_path):
			return Access.PEER
	if app.authentication.default_access and app.authentication.default_access == DefaultAccess.PUBLIC:
		return Access.PUBLIC
	return Access.PRIVATE
