import logging

from shard_core.database.connection import db_conn
from shard_core.database import identities as identities_db
from shard_core.data_model.identity import Identity
from shard_core.service.portal_controller import refresh_profile
from shard_core.util.signals import async_on_first_terminal_add

log = logging.getLogger(__name__)


async def init_default_identity():
    async with db_conn() as conn:
        if await identities_db.count(conn) == 0:
            default_identity = Identity.create(
                "Shard Owner",
                '"Noone wants to manage their own server"\n\nOld outdated saying',
            )
            default_identity.is_default = True
            await identities_db.insert(conn, default_identity.dict())
            log.info(f"created initial default identity {default_identity.id}")
        else:
            row = await identities_db.get_default(conn)
            default_identity = Identity(**row)
        return default_identity


async def make_default(id):
    async with db_conn() as conn:
        last_default_row = await identities_db.get_default(conn)
        last_default = Identity(**last_default_row)
        new_default_row = await identities_db.get_by_id(conn, id)
        if new_default_row:
            new_default = Identity(**new_default_row)
            await identities_db.update(conn, last_default.id, {"is_default": False})
            await identities_db.update(conn, new_default.id, {"is_default": True})
            log.info(f"set as default {new_default.id}")
        else:
            raise KeyError(id)


async def get_default_identity() -> Identity:
    async with db_conn() as conn:
        row = await identities_db.get_default(conn)
        return Identity(**row)


@async_on_first_terminal_add.connect
async def enrich_identity_from_profile(_):
    profile = await refresh_profile()
    if not profile:
        log.warning(
            "Could not enrich default identity from profile because profile could not be obtained."
        )
        return

    async with db_conn() as conn:
        if profile.owner:
            default_row = await identities_db.get_default(conn)
            if default_row:
                await identities_db.update(
                    conn, default_row["id"], {"name": profile.owner}
                )
        if profile.owner_email:
            default_row = await identities_db.get_default(conn)
            if default_row:
                await identities_db.update(
                    conn, default_row["id"], {"email": profile.owner_email}
                )
