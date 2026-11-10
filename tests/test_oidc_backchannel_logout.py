"""Tests for OIDC Back-Channel Logout 1.0 delivery (issue #192).

Follow-up to tests/test_oidc.py's terminal-binding/revocation-on-unpair
coverage: those tests prove the shard's own tokens die on un-pair. These
prove the separate, harder half — that a durable notification gets queued
for the app to kill its own session.

This slice covers enqueue (reading the terminal's live grants and writing
one outbox row per (client_id, sid) BEFORE the un-pair transaction revokes
them / deletes the terminal row), registering a client's logout URI, and
delivery itself: minting a fresh logout_token on every attempt, retrying
with backoff, and the bounded-retry-then-permanently-failed path. The
on_apps_update drain trigger and the discovery-flag gate land in follow-up
commits on this branch.

Real-Immich end-to-end verification is explicitly out of scope here (see the
issue and the freeshard-oidc-identity-campaign skill). All tests use
app_client: no Docker, no real app container, since nothing here needs one.
"""

import base64
import hashlib
import secrets
import time
from urllib.parse import parse_qs, urlparse

import httpx
from httpx import AsyncClient
from joserfc import jwt as joserfc_jwt
from joserfc.jwk import KeySet
from psycopg.rows import dict_row

from shard_core.database.connection import db_conn
from shard_core.database import oidc as db_oidc
from shard_core.database import terminals as db_terminals
from shard_core.service import oidc_backchannel_logout, oidc_provider
from shard_core.util import signals
from tests.util import pair_new_terminal

AUTHORIZE = "public/oidc/authorize"
TOKEN = "public/oidc/token"
JWKS = "public/oidc/jwks"

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
    await ensure_app(app_name)
    return await oidc_provider.register_client(
        app_name, [REDIRECT_URI], backchannel_logout_uri=backchannel_logout_uri
    )


async def set_app_status(name: str, status: str):
    async with db_conn() as conn:
        await conn.execute(
            "UPDATE installed_apps SET status = %s WHERE name = %s", (status, name)
        )


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


async def jwks_keyset(client: AsyncClient) -> KeySet:
    r = await client.get(JWKS)
    assert r.status_code == 200
    return KeySet.import_key_set(r.json())


async def force_due_now(id_: int):
    await rows(
        "UPDATE oidc_backchannel_logout_outbox SET next_attempt_at = now() "
        "WHERE id = %s RETURNING id",
        id_,
    )


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


# --- client registration persists the rendered uri --------------------------


async def test_register_client_renders_and_stores_backchannel_logout_uri(
    app_client: AsyncClient,
):
    from shard_core.data_model.app_meta import OidcMeta
    from dataclasses import dataclass

    @dataclass
    class FakePortal:
        domain: str

    await ensure_app("templated_app")
    meta = OidcMeta(
        redirect_uris=["https://templated_app.{{ portal.domain }}/callback"],
        backchannel_logout_uri="https://templated_app.{{ portal.domain }}/blco",
    )
    ctx = await oidc_provider.ensure_app_client(
        "templated_app", meta, FakePortal(domain="shard.example")
    )

    async with db_conn() as conn:
        stored = await db_oidc.get_client(conn, ctx["client_id"])
    assert stored.backchannel_logout_uri == "https://templated_app.shard.example/blco"


# --- delivery, fresh token per attempt, bounded retry ------------------------


async def test_drain_does_not_wake_a_stopped_app(app_client: AsyncClient, mocker):
    post = mocker.patch("shard_core.service.oidc_backchannel_logout._post_logout_token")
    await pair_new_terminal(app_client, name="phone")
    tid = await terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await set_app_status("bc_app", "stopped")
    await run_code_flow(app_client, oidc_client)
    await unpair(app_client, tid)

    await oidc_backchannel_logout.drain_due_outbox()

    post.assert_not_called()
    entry = (await rows("SELECT * FROM oidc_backchannel_logout_outbox"))[0]
    assert entry["client_id"] == oidc_client.client_id
    assert entry["status"] == "pending"
    assert entry["attempts"] == 0


async def test_drain_delivers_once_the_app_is_running(app_client: AsyncClient, mocker):
    post = mocker.patch(
        "shard_core.service.oidc_backchannel_logout._post_logout_token",
        return_value=None,
    )
    await pair_new_terminal(app_client, name="phone")
    tid = await terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await set_app_status("bc_app", "stopped")
    await run_code_flow(app_client, oidc_client)
    await unpair(app_client, tid)

    await oidc_backchannel_logout.drain_due_outbox()
    post.assert_not_called()

    await set_app_status("bc_app", "running")
    await oidc_backchannel_logout.drain_due_outbox()

    post.assert_called_once()
    assert post.call_args.args[0] == LOGOUT_URI
    entry = (await rows("SELECT * FROM oidc_backchannel_logout_outbox"))[0]
    assert entry["status"] == "delivered"


async def test_on_apps_update_signal_drains_a_due_entry(app_client: AsyncClient, mocker):
    """The spec's actual hook: drain is triggered by on_apps_update, not by
    a test calling drain_due_outbox() directly."""
    post = mocker.patch(
        "shard_core.service.oidc_backchannel_logout._post_logout_token",
        return_value=None,
    )
    await pair_new_terminal(app_client, name="phone")
    tid = await terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await set_app_status("bc_app", "running")
    await run_code_flow(app_client, oidc_client)
    await unpair(app_client, tid)

    await signals.on_apps_update.send_async()

    post.assert_called_once()
    entry = (await rows("SELECT * FROM oidc_backchannel_logout_outbox"))[0]
    assert entry["status"] == "delivered"


async def test_logout_token_is_minted_fresh_on_each_delivery_attempt(
    app_client: AsyncClient, mocker
):
    """The headline regression the issue calls out: Immich enforces
    maxTokenAge '2m', so a token minted once at un-pair and replayed on a
    later retry must never happen — each attempt mints its own."""
    captured: list[str] = []

    async def fake_post(url, token):
        captured.append(token)
        if len(captured) == 1:
            raise httpx.ConnectError("simulated network failure")

    mocker.patch(
        "shard_core.service.oidc_backchannel_logout._post_logout_token",
        side_effect=fake_post,
    )

    await pair_new_terminal(app_client, name="phone")
    tid = await terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await set_app_status("bc_app", "running")
    await run_code_flow(app_client, oidc_client)
    await unpair(app_client, tid)

    await oidc_backchannel_logout.drain_due_outbox()
    assert len(captured) == 1
    entry = (await rows("SELECT * FROM oidc_backchannel_logout_outbox"))[0]
    assert entry["attempts"] == 1
    assert entry["status"] == "pending"

    # Simulate the delay the issue warns about, then force the retry to be
    # due now instead of waiting out the real backoff.
    time.sleep(2)
    await force_due_now(entry["id"])
    await oidc_backchannel_logout.drain_due_outbox()
    assert len(captured) == 2

    keyset = await jwks_keyset(app_client)
    claims1 = joserfc_jwt.decode(captured[0], keyset).claims
    claims2 = joserfc_jwt.decode(captured[1], keyset).claims

    assert captured[0] != captured[1], "logout_token reused across attempts"
    assert claims2["iat"] > claims1["iat"], (
        "second token's iat was not minted fresh at retry time — "
        "a cached/replayed token would fail Immich's maxTokenAge check"
    )
    assert claims1["sid"] == claims2["sid"] == entry["sid"]
    assert claims1["aud"] == claims2["aud"] == [oidc_client.client_id]
    assert "nonce" not in claims1 and "nonce" not in claims2
    assert claims1["events"] == {oidc_provider.BACKCHANNEL_LOGOUT_EVENT: {}}

    final = (await rows("SELECT * FROM oidc_backchannel_logout_outbox"))[0]
    assert final["status"] == "delivered"


async def test_bounded_retry_then_permanent_failure_is_queryable(
    app_client: AsyncClient, mocker
):
    mocker.patch(
        "shard_core.service.oidc_backchannel_logout._post_logout_token",
        side_effect=httpx.ConnectError("always fails"),
    )
    await pair_new_terminal(app_client, name="phone")
    tid = await terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await set_app_status("bc_app", "running")
    await run_code_flow(app_client, oidc_client)
    await unpair(app_client, tid)
    entry_id = (await rows("SELECT * FROM oidc_backchannel_logout_outbox"))[0]["id"]

    for _ in range(oidc_backchannel_logout.MAX_ATTEMPTS):
        await force_due_now(entry_id)
        await oidc_backchannel_logout.drain_due_outbox()

    final = (await rows("SELECT * FROM oidc_backchannel_logout_outbox"))[0]
    assert final["status"] == "failed"
    assert final["attempts"] == oidc_backchannel_logout.MAX_ATTEMPTS
    assert final["last_error"]

    async with db_conn() as conn:
        failed = await db_oidc.get_outbox_entries_by_status(conn, "failed")
    assert [f["id"] for f in failed] == [entry_id]
    assert failed[0]["app_name"] == "bc_app"

    # a permanently-failed entry must not be picked up again
    await force_due_now(entry_id)
    async with db_conn() as conn:
        due = await db_oidc.get_due_outbox_entries(conn)
    assert due == []
