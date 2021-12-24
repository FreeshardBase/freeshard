import logging

from fastapi import HTTPException, APIRouter, Cookie, Response, status
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
