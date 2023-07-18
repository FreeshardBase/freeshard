import logging

import gconf
from requests import HTTPError
from tinydb import Query

from portal_core.database.database import identities_table
from portal_core.model.identity import Identity
from portal_core.model.profile import Profile
from portal_core.service.signed_call import signed_request
from portal_core.util.signals import on_first_terminal_add

log = logging.getLogger(__name__)


def init_default_identity():
	with identities_table() as identities:
		if len(identities) == 0:
			default_identity = Identity.create(
				'Portal Owner',
				'\"Noone wants to manage their own server\"\n\nOld outdated saying')
			default_identity.is_default = True
			identities.insert(
				default_identity.dict()
			)
			log.info(f'created initial default identity {default_identity.id}')
		else:
			default_identity = Identity(**identities.get(Query().is_default == True))  # noqa: E712
		return default_identity


def make_default(id):
	with identities_table() as identities:  # type: Table
		last_default = Identity(**identities.get(Query().is_default == True))  # noqa: E712
		if new_default := Identity(**identities.get(Query().id == id)):
			last_default.is_default = False
			new_default.is_default = True
			identities.update(last_default.dict(), Query().id == last_default.id)
			identities.update(new_default.dict(), Query().id == new_default.id)
			log.info(f'set as default {new_default.id}')
		else:
			KeyError(id)


def get_default_identity() -> Identity:
	with identities_table() as identities:
		return Identity(**identities.get(Query().is_default == True))  # noqa: E712


@on_first_terminal_add.connect
async def enrich_identity_from_profile(_):
	api_url = gconf.get('management.api_url')
	url = f'{api_url}/profile'
	response = await signed_request('GET', url)
	try:
		response.raise_for_status()
	except HTTPError as e:
		log.error(f'Could not enrich default identity from profile because profile could not be obtained: {e}')
		return
	profile = Profile(**response.json())

	with identities_table() as identities:  # type: Table
		if profile.owner:
			identities.update({
				'name': profile.owner,
			}, Query().is_default == True)  # noqa: E712
		if profile.owner_email:
			identities.update({
				'email': profile.owner_email,
			}, Query().is_default == True)  # noqa: E712

