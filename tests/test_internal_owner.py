"""GET /internal/owner: what an app sidecar may read about the owner.

The invariant under test is that the endpoint exposes only the owner's identity
and a *verified* address — never pending_email or the confirmation-token fields.
That is what lets a sidecar trust the address for OIDC email matching (see
tests/test_owner_email.py for how users.email earns "verified").
"""

from datetime import datetime, timedelta, timezone

from httpx import AsyncClient

from shard_core.database import users as db_users
from shard_core.database.connection import db_conn

OWNER = "internal/owner"


async def get_owner():
    async with db_conn() as conn:
        return await db_users.get_owner(conn)


async def set_owner_fields(fields: dict):
    async with db_conn() as conn:
        await db_users.update(conn, (await get_owner()).id, fields)


async def test_returns_verified_address_and_identity(app_client: AsyncClient):
    await set_owner_fields({"email": "verified@freeshard.net"})
    owner = await get_owner()

    response = await app_client.get(OWNER)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == owner.id
    assert body["username"] == owner.username
    assert body["display_name"] == owner.display_name
    assert body["email"] == "verified@freeshard.net"


async def test_email_is_null_when_only_pending(app_client: AsyncClient):
    """A pending address is unverified, so it must not surface as the email."""
    await set_owner_fields(
        {
            "pending_email": "candidate@freeshard.net",
            "email_token_hash": "deadbeef",
            "email_token_expires": datetime.now(timezone.utc) + timedelta(hours=1),
        }
    )

    body = (await app_client.get(OWNER)).json()

    assert body["email"] is None


async def test_email_is_null_when_no_address(app_client: AsyncClient):
    """A fresh owner has verified nothing."""
    body = (await app_client.get(OWNER)).json()

    assert body["email"] is None


async def test_never_leaks_pending_or_token_fields(app_client: AsyncClient):
    await set_owner_fields(
        {
            "email": "verified@freeshard.net",
            "pending_email": "candidate@freeshard.net",
            "email_token_hash": "deadbeef",
            "email_token_expires": datetime.now(timezone.utc) + timedelta(hours=1),
        }
    )

    body = (await app_client.get(OWNER)).json()

    assert set(body) == {"id", "username", "display_name", "email"}
    assert "pending_email" not in body
    assert "email_token_hash" not in body
    assert "email_token_expires" not in body
