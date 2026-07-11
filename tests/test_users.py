from httpx import AsyncClient

from shard_core.data_model.user import Role, User
from shard_core.database.connection import db_conn
from shard_core.database import identities as db_identities
from shard_core.database import terminals as db_terminals
from shard_core.database import users as db_users
from shard_core.service import identity, user
from tests.util import pair_new_terminal


async def test_ensure_owner_user_creates_owner_from_default_identity(db):
    default_identity = await identity.init_default_identity()

    owner = await user.ensure_owner_user()

    assert isinstance(owner, User)
    assert isinstance(owner.id, int)
    assert owner.role == Role.OWNER
    assert owner.username == "owner"
    assert owner.display_name == default_identity.name
    assert owner.email == f"owner@{default_identity.domain}"
    assert owner.disabled is False


async def test_ensure_owner_user_keeps_identity_email(db):
    default_identity = await identity.init_default_identity()
    async with db_conn() as conn:
        await db_identities.update(
            conn, default_identity.id, {"email": "max@freeshard.net"}
        )

    owner = await user.ensure_owner_user()

    assert owner.email == "max@freeshard.net"


async def test_ensure_owner_user_is_idempotent(db):
    await identity.init_default_identity()

    first = await user.ensure_owner_user()
    second = await user.ensure_owner_user()

    assert first.id == second.id
    async with db_conn() as conn:
        assert await db_users.count(conn) == 1


async def test_ensure_owner_user_backfills_missing_email(db):
    """Migration-created owners (existing shards) start without a synthesized
    email; ensure_owner_user fills it on the next startup."""
    default_identity = await identity.init_default_identity()
    async with db_conn() as conn:
        await db_users.insert(
            conn,
            {
                "username": "owner",
                "display_name": default_identity.name,
                "email": None,
                "role": Role.OWNER.value,
            },
        )  # simulates the 0002 SQL backfill (no synthesized email)

    owner = await user.ensure_owner_user()

    assert owner.email == f"owner@{default_identity.domain}"


async def test_pairing_binds_terminal_to_owner(app_client: AsyncClient):
    await pair_new_terminal(app_client, "T1")

    async with db_conn() as conn:
        owner = await db_users.get_owner(conn)
        terminal = await db_terminals.get_by_name(conn, "T1")
    assert terminal["user_id"] == owner.id
