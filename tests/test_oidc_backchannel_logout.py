"""Tests for OIDC Back-Channel Logout 1.0 delivery (issue #192).

Follow-up to tests/test_oidc.py's terminal-binding/revocation-on-unpair
coverage: those tests prove the shard's own tokens die on un-pair. These
prove the separate, harder half — that a durable notification gets queued
for the app to kill its own session.

This first slice covers enqueue: reading the terminal's live grants and
writing one outbox row per (client_id, sid) BEFORE the un-pair transaction
revokes them / deletes the terminal row. Delivery, retry, drain-on-RUNNING
and discovery-flag coverage land in follow-up commits on this branch.

Real-Immich end-to-end verification is explicitly out of scope here (see the
issue and the freeshard-oidc-identity-campaign skill). All tests use
app_client: no Docker, no real app container, since nothing here needs one.
"""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

from httpx import AsyncClient
from psycopg.rows import dict_row

from shard_core.database.connection import db_conn
from shard_core.database import terminals as db_terminals
from shard_core.service import oidc_provider
from tests.util import pair_new_terminal

AUTHORIZE = "public/oidc/authorize"
TOKEN = "public/oidc/token"

REDIRECT_URI = "http://app.testserver/oauth/callback"
LOGOUT_URI = "https://bc_app.example/backchannel-logout"


# --- shared helpers (deliberately not imported from tests/test_oidc.py —
# each test module in this repo is self-contained; see e.g. that module's
# own near-identical copies) ------------------------------------------------


def s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def rows(sql: str, *args) -> list[dict]:
    async with db_conn() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, args)
            return await cur.fetchall()


async def ensure_app(name: str, status: str = "stopped"):
    async with db_conn() as conn:
        await conn.execute(
            "INSERT INTO installed_apps (name, status) VALUES (%s, %s) "
            "ON CONFLICT (name) DO UPDATE SET status = EXCLUDED.status",
            (name, status),
        )


async def make_client(app_name: str, backchannel_logout_uri: str | None = LOGOUT_URI):
    """register_client doesn't accept a backchannel_logout_uri kwarg yet in
    this slice (that lands with client-registration persistence) — set it
    directly on the already-migrated column instead."""
    await ensure_app(app_name)
    client = await oidc_provider.register_client(app_name, [REDIRECT_URI])
    async with db_conn() as conn:
        await conn.execute(
            "UPDATE oidc_clients SET backchannel_logout_uri = %s WHERE client_id = %s",
            (backchannel_logout_uri, client.client_id),
        )
    return client.model_copy(update={"backchannel_logout_uri": backchannel_logout_uri})


async def terminal_id(name: str) -> str:
    async with db_conn() as conn:
        return (await db_terminals.get_by_name(conn, name))["id"]


async def unpair(client: AsyncClient, id_: str):
    r = await client.delete(f"protected/terminals/id/{id_}")
    assert r.status_code == 204, r.text


async def run_code_flow(client: AsyncClient, oidc_client) -> dict:
    verifier = secrets.token_urlsafe(32)
    params = {
        "response_type": "code",
        "client_id": oidc_client.client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": "openid profile email",
        "state": secrets.token_urlsafe(8),
        "nonce": secrets.token_urlsafe(8),
        "code_challenge": s256(verifier),
        "code_challenge_method": "S256",
    }
    r = await client.get(AUTHORIZE, params=params)
    assert r.status_code == 302, r.text
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }
    auth = None
    if oidc_client.client_secret is not None:
        auth = (oidc_client.client_id, oidc_client.client_secret)
    else:
        data["client_id"] = oidc_client.client_id
    r = await client.post(TOKEN, data=data, auth=auth)
    assert r.status_code == 200, r.text
    return r.json()


async def outbox_row(client_id: str, sid: str) -> dict:
    found = await rows(
        "SELECT * FROM oidc_backchannel_logout_outbox WHERE client_id = %s AND sid = %s",
        client_id,
        sid,
    )
    assert len(found) == 1, found
    return found[0]


# --- enqueue on un-pair ------------------------------------------------------


async def test_unpair_enqueues_a_delivery_for_a_live_grant_with_a_logout_uri(
    app_client: AsyncClient,
):
    await pair_new_terminal(app_client, name="phone")
    tid = await terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await run_code_flow(app_client, oidc_client)

    token_row = (await rows("SELECT * FROM oidc_tokens WHERE terminal_id = %s", tid))[0]

    await unpair(app_client, tid)

    entry = await outbox_row(oidc_client.client_id, token_row["sid"])
    assert entry["status"] == "pending"
    assert entry["attempts"] == 0
    assert entry["terminal_id"] == tid
    assert entry["user_sub"] == token_row["user_sub"]


async def test_unpair_enqueues_nothing_for_a_client_without_a_logout_uri(
    app_client: AsyncClient,
):
    await pair_new_terminal(app_client, name="phone")
    tid = await terminal_id("phone")
    oidc_client = await make_client("no_logout_app", backchannel_logout_uri=None)
    await run_code_flow(app_client, oidc_client)

    await unpair(app_client, tid)

    assert await rows("SELECT * FROM oidc_backchannel_logout_outbox") == []


async def test_unpair_enqueues_nothing_for_a_terminal_with_no_grants(
    app_client: AsyncClient,
):
    await pair_new_terminal(app_client, name="phone")
    tid = await terminal_id("phone")
    await make_client("bc_app")  # registered, but never authorized by "phone"

    await unpair(app_client, tid)

    assert await rows("SELECT * FROM oidc_backchannel_logout_outbox") == []


async def test_live_grants_must_be_read_before_revocation(app_client: AsyncClient):
    """Regression for the exact ordering bug the issue calls out: reading
    live grants AFTER oidc.revoke_for_terminal has run finds nothing, because
    revoke_for_terminal marks them revoked and get_live_grants_for_terminal
    filters on NOT revoked. Enqueue must run first."""
    from shard_core.database import oidc as db_oidc_module

    await pair_new_terminal(app_client, name="phone")
    tid = await terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await run_code_flow(app_client, oidc_client)

    async with db_conn() as conn:
        before = await db_oidc_module.get_live_grants_for_terminal(conn, tid)
        assert len(before) == 1, "the grant must be visible before revocation"

        await db_oidc_module.revoke_for_terminal(conn, tid)

        after = await db_oidc_module.get_live_grants_for_terminal(conn, tid)
        assert after == [], "revoked grants must no longer read as live"
