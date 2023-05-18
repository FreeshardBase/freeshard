import logging

from fastapi import APIRouter, Response, Request

from portal_core.service import management as mngt_service
from portal_core.web.util import ALL_HTTP_METHODS

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/management',
)


@router.api_route('/{rest:path}', methods=ALL_HTTP_METHODS)
async def call_management(rest: str, request: Request):
	body = await request.body()
	response = mngt_service.call_management(rest, request.method, body=body)
	return Response(status_code=response.status_code, content=response.content)
