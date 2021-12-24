import logging

from tinydb import Query
from tinydb.table import Table

from portal_core import get_db, Identity
from portal_core.database import identities_table

log = logging.getLogger(__name__)


def init_default_identity():
	with get_db() as db:
		if len(db.table('identities')) == 0:
			default_identity = Identity.create('default_identity', 'created at first startup')
			default_identity.is_default = True
			db.table('identities').insert(
				default_identity.dict()
			)
			log.info(f'created initial default identity {default_identity.id}')
		else:
			default_identity = db.table('identities').get(Query().is_default)
		return default_identity


def make_default(name):
	with identities_table() as identities:  # type: Table
		last_default = Identity(**identities.get(Query().is_default == True))
		if new_default := Identity(**identities.get(Query().name == name)):
			last_default.is_default = False
			new_default.is_default = True
			identities.update(last_default.dict(), Query().name == last_default.name)
			identities.update(new_default.dict(), Query().name == new_default.name)
			log.info(f'set as default {new_default.name}')
		else:
			KeyError(name)
