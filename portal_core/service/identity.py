import logging

import gconf
from requests import HTTPError
from tinydb import Query
from tinydb.table import Table

from portal_core.database.database import identities_table
from portal_core.model.identity import Identity
from portal_core.model.profile import Profile
from portal_core.service.signed_call import signed_request

log = logging.getLogger(__name__)


def init_default_identity():
	with identities_table() as identities:
		if len(identities) == 0:
			default_identity = Identity.create('default_identity', 'created at first startup')
			default_identity.is_default = True
			identities.insert(
				default_identity.dict()
			)
			log.info(f'created initial default identity {default_identity.id}')
		else:
			default_identity = identities.get(Query().is_default == True)
		return default_identity


def make_default(id):
	with identities_table() as identities:  # type: Table
		last_default = Identity(**identities.get(Query().is_default == True))
		if new_default := Identity(**identities.get(Query().id == id)):
			last_default.is_default = False
			new_default.is_default = True
			identities.update(last_default.dict(), Query().name == last_default.name)
			identities.update(new_default.dict(), Query().name == new_default.name)
			log.info(f'set as default {new_default.id}')
		else:
			KeyError(id)


def get_default_identity() -> Identity:
	with identities_table() as identities:
		return Identity(**identities.get(Query().is_default == True))


def enrich_identity_from_profile():
	# todo: remove if no longer needed
	api_url = gconf.get('management.api_url')
	url = f'{api_url}/profile'
	response = signed_request('GET', url)
	try:
		response.raise_for_status()
	except HTTPError:
		return
	profile = Profile(**response.json())

	with identities_table() as identities:  # type: Table
		identities.update({
			'name': profile.owner,
			'email': profile.owner_email,
		}, Query().is_default == True)
