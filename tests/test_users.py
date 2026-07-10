from httpx import AsyncClient

from shard_core.data_model.terminal import Terminal
from shard_core.database.connection import db_conn
from shard_core.database import identities as db_identities
from shard_core.database import terminals as db_terminals
from shard_core.database import users as db_users
from shard_core.service import identity, user
from tests.util import pair_new_terminal


async def test_ensure_owner_user_creates_owner_from_default_identity(db):
    default_identity = await identity.init_default_identity()

    await user.ensure_owner_user()

    async with db_conn() as conn:
        owner = await db_users.get_owner(conn)
    assert owner["id"] == default_identity.id
    assert owner["role"] == "owner"
    assert owner["username"] == "owner"
    assert owner["display_name"] == default_identity.name
    assert owner["email"] == f"owner@{default_identity.domain}"
    assert owner["disabled"] is False


async def test_ensure_owner_user_keeps_identity_email(db):
    default_identity = await identity.init_default_identity()
    async with db_conn() as conn:
        await db_identities.update(
            conn, default_identity.id, {"email": "max@freeshard.net"}
        )

    await user.ensure_owner_user()

    async with db_conn() as conn:
        owner = await db_users.get_owner(conn)
    assert owner["email"] == "max@freeshard.net"


async def test_ensure_owner_user_is_idempotent(db):
    await identity.init_default_identity()

    await user.ensure_owner_user()
    await user.ensure_owner_user()

    async with db_conn() as conn:
        assert await db_users.count(conn) == 1


async def test_ensure_owner_user_backfills_terminal_user_id(db):
    await identity.init_default_identity()
    legacy_terminal = Terminal.create("legacy")
    async with db_conn() as conn:
        await db_terminals.insert(conn, legacy_terminal.model_dump())

    await user.ensure_owner_user()

    async with db_conn() as conn:
        owner = await db_users.get_owner(conn)
        row = await db_terminals.get_by_id(conn, legacy_terminal.id)
    assert row["user_id"] == owner["id"]


async def test_pairing_binds_terminal_to_owner(app_client: AsyncClient):
    await pair_new_terminal(app_client, "T1")

    async with db_conn() as conn:
        owner = await db_users.get_owner(conn)
        terminal = await db_terminals.get_by_name(conn, "T1")
    assert terminal["user_id"] == owner["id"]
