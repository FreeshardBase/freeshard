import logging

import gconf
from fastapi import APIRouter, Response, Request

from portal_core.service.signed_call import signed_request
from portal_core.web.util import ALL_HTTP_METHODS

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/management',
)


@router.api_route('/{rest:path}', methods=ALL_HTTP_METHODS)
async def call_management(rest: str, request: Request):
	api_url = gconf.get('management.api_url')
	url = f'{api_url}/{rest}'
	log.debug(f'call to {request.method} {url}')

	body = await request.body()
	response = signed_request(request.method, url, data=body)
	return Response(status_code=response.status_code, content=response.content)
