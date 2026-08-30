import logging

from shard_core.data_model.identity import Identity
from shard_core.data_model.user import Role, User
from shard_core.database.connection import db_conn
from shard_core.database import identities as db_identities
from shard_core.database import users as db_users

log = logging.getLogger(__name__)


async def ensure_owner_user() -> User:
    """Ensure the shard owner exists as a user.

    The owner user is created by the 0002 migration on shards that already
    have an identity; on fresh shards it is created here, right after the
    default identity. A fresh owner has no address: users.email is verified by
    definition, and nothing has been verified yet.
    Idempotent — called on every startup, before any pairing can happen.
    """
    async with db_conn() as conn:
        owner = await db_users.get_owner(conn)
        if owner is None:
            identity_row = await db_identities.get_default(conn)
            identity = Identity(**identity_row)
            owner = await db_users.insert(
                conn,
                {
                    "username": "owner",
                    "display_name": identity.name,
                    "email": None,
                    "role": Role.OWNER.value,
                },
            )
            log.info(f"created owner user {owner.id}")
    return owner
