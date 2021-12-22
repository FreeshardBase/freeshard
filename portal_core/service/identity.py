import logging

import gconf
from tinydb import Query

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
