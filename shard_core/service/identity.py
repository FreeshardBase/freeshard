import logging

from shard_core.database.connection import db_conn
from shard_core.database import identities as db_identities
from shard_core.database import users as db_users
from shard_core.data_model.identity import Identity
from shard_core.service import owner_email
from shard_core.service.portal_controller import refresh_profile
from shard_core.util.signals import async_on_first_terminal_add, on_identity_update

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
            await on_identity_update.send_async()
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
    await on_identity_update.send_async()


async def update_identity(id: str, update_data: dict) -> Identity:
    async with db_conn() as conn:
        updated = await db_identities.update(conn, id, update_data)
    await on_identity_update.send_async()
    return Identity(**updated)


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
        if default and profile.owner:
            await update_identity(default["id"], {"name": profile.owner})

        owner = await db_users.get_owner(conn) if profile.owner_email else None

    if owner and owner.email is None:
        # set_email() is what actually mints a token and sends the
        # confirmation — writing pending_email directly, as this used to do,
        # created a candidate nothing ever notified the owner about. This
        # handler re-fires whenever the last terminal is re-paired, and
        # set_email() replacing any existing candidate is exactly the right
        # behavior there too: the token is bound to whatever pending_email
        # holds when it is opened, so a new candidate must retire the old one.
        try:
            await owner_email.set_email(owner, profile.owner_email)
        except (owner_email.SendRateLimited, owner_email.DeliveryFailed) as e:
            # This handler runs synchronously inside the pairing request, and
            # pairing a device must succeed no matter what happens to this
            # best-effort enrichment. Fall back to the old raw write so the
            # owner at least sees a pending candidate in Settings and can
            # resend manually, rather than ending up with nothing at all.
            log.warning(
                f"could not send a verification email while enriching identity "
                f"from profile, falling back to an unsent candidate: {e}"
            )
            async with db_conn() as conn:
                await db_users.update(
                    conn,
                    owner.id,
                    {
                        "pending_email": profile.owner_email,
                        "email_token_hash": None,
                        "email_token_expires": None,
                    },
                )
