import logging

import gconf
from fastapi import APIRouter

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
