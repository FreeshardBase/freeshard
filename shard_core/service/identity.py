import logging

from shard_core.db import identities
from shard_core.db.db_connection import db_conn
from shard_core.data_model.identity import Identity
from shard_core.service.portal_controller import refresh_profile
from shard_core.util.signals import async_on_first_terminal_add

log = logging.getLogger(__name__)


async def init_default_identity():
    async with db_conn() as conn:
        if await identities.count(conn) == 0:
            default_identity = Identity.create(
                "Shard Owner",
                '"Noone wants to manage their own server"\n\nOld outdated saying',
            )
            default_identity.is_default = True
            await identities.insert(conn, default_identity)
            log.info(f"created initial default identity {default_identity.id}")
        else:
            default_identity = await identities.get_default(conn)
        return default_identity


async def make_default(id):
    async with db_conn() as conn:
        last_default = await identities.get_default(conn)
        
        new_default = await identities.get_by_id(conn, id)
        if new_default:
            await identities.update(conn, last_default.id, is_default=False)
            await identities.update(conn, id, is_default=True)
            log.info(f"set as default {id}")
        else:
            raise KeyError(id)


async def get_default_identity() -> Identity:
    async with db_conn() as conn:
        return await identities.get_default(conn)


@async_on_first_terminal_add.connect
async def enrich_identity_from_profile(_):
    profile = await refresh_profile()
    if not profile:
        log.warning(
            "Could not enrich default identity from profile because profile could not be obtained."
        )
        return

    async with db_conn() as conn:
        default_identity = await identities.get_default(conn)
        await identities.update(
            conn,
            default_identity.id,
            name=profile.owner if profile.owner else None,
            email=profile.owner_email if profile.owner_email else None
        )
