import logging

from requests import HTTPError
from sqlalchemy import update
from sqlalchemy.exc import MultipleResultsFound, NoResultFound
from sqlmodel import select, col
from tinydb import Query

from portal_core.database.database import session
from portal_core.database.models import Identity
from portal_core.old_database.database import identities_table
from portal_core.service.portal_controller import refresh_profile
from portal_core.util.signals import async_on_first_terminal_add

log = logging.getLogger(__name__)


def init_default_identity():
	with session() as _session:
		statement = select(Identity).where(col(Identity.is_default) == True)
		try:
			default_identity = _session.exec(statement).one()
		except MultipleResultsFound:
			log.error('Multiple default identities found')
			raise
		except NoResultFound:
			default_identity = Identity.create(
				'Portal Owner',
				'\"Noone wants to manage their own server\"\n\nOld outdated saying')
			default_identity.is_default = True
			_session.add(default_identity)
			_session.commit()
			log.info(f'created initial default identity {default_identity.id}')

		return default_identity


def make_default(id):
	with session() as _session:
		try:
			_session.exec(select(Identity).where(col(Identity.id) == id)).one()
		except NoResultFound as e:
			log.error(f'Identity with id {id} not found')
			raise KeyError(id) from e

		_session.exec(update(Identity).values({Identity.is_default: False}))
		_session.exec(update(Identity).where(col(Identity.id) == id).values({Identity.is_default: True}))
		_session.commit()
		log.info(f'set as default {id}')


def get_default_identity() -> Identity:
	with session() as _session:
		statement = select(Identity).where(col(Identity.is_default) == True)
		try:
			return _session.exec(statement).one()
		except MultipleResultsFound:
			log.error('Multiple default identities found')
			raise
		except NoResultFound:
			log.error('No default identity found')
			raise


@async_on_first_terminal_add.connect
async def enrich_identity_from_profile(_):
	try:
		profile = await refresh_profile()
	except HTTPError as e:
		log.error(f'Could not enrich default identity from profile because profile could not be obtained: {e}')
		return

	with identities_table() as identities:  # type: Table
		if profile.owner:
			identities.update({
				'name': profile.owner,
			}, Query().is_default == True)  # noqa: E712
		if profile.owner_email:
			identities.update({
				'email': profile.owner_email,
			}, Query().is_default == True)  # noqa: E712
