import logging

from shard_core.database.connection import db_conn
from shard_core.database import identities as db_identities
from shard_core.data_model.identity import Identity
from shard_core.service.portal_controller import refresh_profile
from shard_core.util.signals import async_on_first_terminal_add

log = logging.getLogger(__name__)


async def init_default_identity():
    async with db_conn() as conn:
        if await db_identities.count(conn) == 0:
            default_identity = Identity.create(
                "Shard Owner",
                '"Noone wants to manage their own server"\n\nOld outdated saying',
            )
            default_identity.is_default = True
            await db_identities.insert(conn, default_identity.model_dump())
            log.info(f"created initial default identity {default_identity.id}")
            return default_identity
        else:
            row = await db_identities.get_default(conn)
            return Identity(**row)


async def make_default(id):
    async with db_conn() as conn:
        last_default_row = await db_identities.get_default(conn)
        if not last_default_row:
            raise KeyError("no default identity found")
        new_default_row = await db_identities.get_by_id(conn, id)
        if not new_default_row:
            raise KeyError(id)
        await db_identities.update(conn, last_default_row["id"], {"is_default": False})
        await db_identities.update(conn, id, {"is_default": True})
        log.info(f"set as default {id}")


async def get_default_identity() -> Identity:
    async with db_conn() as conn:
        row = await db_identities.get_default(conn)
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
        default = await db_identities.get_default(conn)
        if not default:
            return
        update_data = {}
        if profile.owner:
            update_data["name"] = profile.owner
        if profile.owner_email:
            update_data["email"] = profile.owner_email
        if update_data:
            await db_identities.update(conn, default["id"], update_data)
