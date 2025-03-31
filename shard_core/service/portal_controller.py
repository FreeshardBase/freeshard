import logging
from requests.exceptions import HTTPError

import gconf

from shard_core.model import profile
from shard_core.model.backend.portal_backup import SasUrlResponse
from shard_core.model.backend.portal_meta import PortalMetaExt
from shard_core.service.signed_call import signed_request

log = logging.getLogger(__name__)


async def call_portal_controller(path: str, method: str = 'GET', body: bytes = None):
	controller_base_url = gconf.get('portal_controller.base_url')
	url = f'{controller_base_url}/api/{path}'
	log.debug(f'call to {method} {url}')
	return await signed_request(method, url, data=body)


async def refresh_profile() -> profile.Profile | None:
	response = await call_portal_controller('portals/self')
	try:
		response.raise_for_status()
	except HTTPError:
		if response.status_code == 401:
			log.warning('profile not found, setting to None')
			profile.set_profile(None)
			return None
		else:
			raise
	meta = PortalMetaExt.parse_obj(response.json())
	profile_ = profile.Profile.from_portal(meta)
	profile.set_profile(profile_)
	log.debug('refreshed profile')
	return profile_


async def get_backup_sas_url() -> SasUrlResponse:
	response = await call_portal_controller('portal_backup/backup_sas_url')
	response.raise_for_status()
	return SasUrlResponse.parse_obj(response.json())
