import logging

from fastapi import APIRouter, Response, Request

from portal_core.model import profile
from portal_core.service import management as mngt_service, portal_controller
from portal_core.web.util import ALL_HTTP_METHODS

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/management',
)


@router.get('/profile', response_model=profile.Profile)
async def get_profile(refresh: bool = False):
	if refresh:
		p = await portal_controller.refresh_profile()
	else:
		try:
			p = profile.get_profile()
		except KeyError:
			p = await portal_controller.refresh_profile()
	return p


@router.api_route('/{rest:path}', methods=ALL_HTTP_METHODS)
async def call_management(rest: str, request: Request):
	body = await request.body()
	response = await mngt_service.call_management(rest, request.method, body=body)
	return Response(status_code=response.status_code, content=response.content)
