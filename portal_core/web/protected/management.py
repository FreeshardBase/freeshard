import logging
from typing import Optional

import gconf
from fastapi import APIRouter, Response
from pydantic import BaseModel

from portal_core import signed_request
from portal_core.model.profile import Profile

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/management',
)


@router.get('/profile', response_model=Profile)
def profile():
	api_url = gconf.get('management.api_url')
	url = f'{api_url}/profile'
	log.debug(f'Getting profile from {url}')
	response = signed_request('GET', url)
	log.debug(f'profile response status: {response.status_code}')
	response.raise_for_status()
	return Profile(**response.json())


class PortalConfig(BaseModel):
	size: Optional[str]


@router.put('/config')
def put_config(config: PortalConfig):
	api_url = gconf.get('management.api_url')
	url = f'{api_url}/config'
	log.debug(f'Setting config to {config.json(indent=2)}')
	response = signed_request('PUT', url, json=config.dict())
	return Response(status_code=response.status_code)
