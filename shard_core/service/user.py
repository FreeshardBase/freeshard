import logging

from shard_core.data_model.identity import Identity
from shard_core.database.connection import db_conn
from shard_core.database import identities as db_identities
from shard_core.database import terminals as db_terminals
from shard_core.database import users as db_users

log = logging.getLogger(__name__)


async def ensure_owner_user():
    """Ensure the shard owner exists as a user and all terminals are bound to a user.

    The owner user is derived from the default identity; its id doubles as the
    OIDC subject. Idempotent — called on every startup.
    """
    async with db_conn() as conn:
        owner = await db_users.get_owner(conn)
        if owner is None:
            identity_row = await db_identities.get_default(conn)
            identity = Identity(**identity_row)
            owner = await db_users.insert(
                conn,
                {
                    "id": identity.id,
                    "username": "owner",
                    "display_name": identity.name,
                    "email": identity.email or f"owner@{identity.domain}",
                    "role": "owner",
                },
            )
            log.info(f"created owner user {owner['id']}")
        await db_terminals.set_user_id_where_null(conn, owner["id"])
