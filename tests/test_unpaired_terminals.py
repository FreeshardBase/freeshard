"""Tests for keeping unpaired devices until their app lockouts are delivered,
exposing that per-app state, and surviving app uninstall.

A lockout is one back-channel logout outbox row: one notification for one app
session of an unpaired device. An unpaired device is kept (flagged
unpaired_at) and hidden from every connected-device path until its lockouts
are delivered, then reaped. See the issue (#314), service/terminal_lockouts.py
and web/protected/terminals.py.

Like tests/test_oidc_backchannel_logout.py these use app_client (no Docker):
nothing here needs a real container, only outbox rows and app status.
"""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import AsyncClient
from joserfc import jwt as joserfc_jwt
from joserfc.jwk import KeySet
from psycopg.rows import dict_row

from shard_core.database.connection import db_conn
from shard_core.database import terminals as db_terminals
from shard_core.service import (
    oidc_backchannel_barrier as barrier,
    oidc_backchannel_logout,
    oidc_provider,
)
from shard_core.util import signals
from tests.util import pair_new_terminal

AUTHORIZE = "public/oidc/authorize"
TOKEN = "public/oidc/token"
JWKS = "public/oidc/jwks"
REDIRECT_URI = "http://app.testserver/oauth/callback"
LOGOUT_URI = "https://bc_app.example/backchannel-logout"


@pytest.fixture(autouse=True)
def _reset_barrier_state():
    for state in (barrier._pending_apps, barrier._locks, barrier._hold_since, barrier._failed_open):
        state.clear()
    yield


async def rows(sql: str, *args) -> list[dict]:
    async with db_conn() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, args)
            return await cur.fetchall()


def s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def ensure_app(name: str, status: str = "stopped"):
    async with db_conn() as conn:
        await conn.execute(
            "INSERT INTO installed_apps (name, status) VALUES (%s, %s) "
            "ON CONFLICT (name) DO UPDATE SET status = EXCLUDED.status",
            (name, status),
        )


async def make_client(app_name: str = "bc_app", backchannel_logout_uri: str | None = LOGOUT_URI):
    await ensure_app(app_name)
    return await oidc_provider.register_client(app_name, [REDIRECT_URI], backchannel_logout_uri=backchannel_logout_uri)


async def set_app_status(name: str, status: str):
    async with db_conn() as conn:
        await conn.execute("UPDATE installed_apps SET status = %s WHERE name = %s", (status, name))


async def connected_terminal_id(name: str) -> str:
    async with db_conn() as conn:
        return (await db_terminals.get_connected_by_name(conn, name))["id"]


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


async def jwks_keyset(client: AsyncClient) -> KeySet:
    r = await client.get(JWKS)
    assert r.status_code == 200
    return KeySet.import_key_set(r.json())


async def force_all_due_now():
    await rows("UPDATE oidc_backchannel_logout_outbox SET next_attempt_at = now() RETURNING id")


async def get_unpaired(client: AsyncClient) -> list[dict]:
    r = await client.get("protected/terminals/unpaired")
    assert r.status_code == 200, r.text
    return r.json()


# --- the flag filter ---------------------------------------------------------


async def test_unpaired_device_is_rejected_hidden_and_uncounted(app_client: AsyncClient):
    await pair_new_terminal(app_client, name="phone")
    phone_jwt = app_client.cookies["authorization"]
    tid = await connected_terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await run_code_flow(app_client, oidc_client)

    await unpair(app_client, tid)  # keeps the row: it owes a lockout

    # 1. the device's terminal JWT is rejected
    app_client.cookies = {"authorization": phone_jwt}
    r = await app_client.get("internal/authenticate_terminal")
    assert r.status_code == 401

    # 2. absent from GET /protected/terminals and present in /unpaired
    listed = (await app_client.get("protected/terminals")).json()
    assert all(t["id"] != tid for t in listed)
    assert [d["id"] for d in await get_unpaired(app_client)] == [tid]

    # 3. absent from the terminals_update broadcast (its data source)
    async with db_conn() as conn:
        assert all(t["id"] != tid for t in await db_terminals.list_connected(conn))
        # 4. does not count for the first-pairing owner check
        assert await db_terminals.count_connected(conn) == 0


# --- unpair with and without lockouts ---------------------------------------


async def test_unpair_with_lockouts_lists_state_then_is_gone_once_delivered(
    app_client: AsyncClient, mocker
):
    post = mocker.patch(
        "shard_core.service.oidc_backchannel_logout._post_logout_token", return_value=None
    )
    await pair_new_terminal(app_client, name="phone")
    tid = await connected_terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await set_app_status("bc_app", "stopped")
    await run_code_flow(app_client, oidc_client)

    await unpair(app_client, tid)

    [dev] = await get_unpaired(app_client)
    assert dev["id"] == tid
    assert dev["paired_at"] is not None
    assert dev["unpaired_at"] is not None
    # app installed but not running
    assert dev["lockouts"] == [{"app_name": "bc_app", "state": "waiting_for_start"}]

    await set_app_status("bc_app", "running")
    await oidc_backchannel_logout.drain_due_outbox()

    post.assert_called_once()
    assert await get_unpaired(app_client) == []
    assert await rows("SELECT * FROM terminals WHERE id = %s", tid) == []
    assert await rows("SELECT * FROM oidc_backchannel_logout_outbox") == []


async def test_unpair_without_lockouts_deletes_the_device_immediately(app_client: AsyncClient):
    await pair_new_terminal(app_client, name="phone")
    tid = await connected_terminal_id("phone")
    # an app with no backchannel_logout_uri — nothing to deliver to
    oidc_client = await make_client("plain_app", backchannel_logout_uri=None)
    await run_code_flow(app_client, oidc_client)

    await unpair(app_client, tid)

    assert await rows("SELECT * FROM terminals WHERE id = %s", tid) == []
    assert await get_unpaired(app_client) == []


# --- survives uninstall, delivered against the reinstalled client -----------


async def test_lockout_survives_uninstall_and_targets_the_reinstalled_client(
    app_client: AsyncClient, mocker
):
    captured: list[str] = []

    async def fake_post(url, token):
        captured.append(token)

    mocker.patch(
        "shard_core.service.oidc_backchannel_logout._post_logout_token", side_effect=fake_post
    )
    await pair_new_terminal(app_client, name="phone")
    tid = await connected_terminal_id("phone")
    old_client = await make_client("bc_app")
    await run_code_flow(app_client, old_client)
    await unpair(app_client, tid)

    # uninstall: dropping the installed_apps row cascades the oidc_clients row.
    async with db_conn() as conn:
        await conn.execute("DELETE FROM installed_apps WHERE name = 'bc_app'")
    assert await rows("SELECT * FROM oidc_clients WHERE app_name = 'bc_app'") == []

    # the lockout survives, now blocked on the app being installed again
    [dev] = await get_unpaired(app_client)
    assert dev["lockouts"] == [{"app_name": "bc_app", "state": "waiting_for_install"}]

    # reinstall registers a fresh client_id
    new_client = await make_client("bc_app")
    assert new_client.client_id != old_client.client_id
    await set_app_status("bc_app", "running")

    await oidc_backchannel_logout.drain_due_outbox()

    assert len(captured) == 1
    claims = joserfc_jwt.decode(captured[0], await jwks_keyset(app_client)).claims
    assert claims["aud"] == [new_client.client_id], "token must target the reinstalled client"
    assert await rows("SELECT * FROM oidc_backchannel_logout_outbox") == []
    assert await rows("SELECT * FROM terminals WHERE id = %s", tid) == []


# --- retry and dismiss -------------------------------------------------------


async def test_retry_resets_failed_lockouts(app_client: AsyncClient, mocker):
    mocker.patch(
        "shard_core.service.oidc_backchannel_logout._post_logout_token",
        side_effect=httpx.ConnectError("always fails"),
    )
    await pair_new_terminal(app_client, name="phone")
    tid = await connected_terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await set_app_status("bc_app", "running")
    await run_code_flow(app_client, oidc_client)
    await unpair(app_client, tid)

    for _ in range(oidc_backchannel_logout.MAX_ATTEMPTS):
        await force_all_due_now()
        await oidc_backchannel_logout.drain_due_outbox()

    assert (await rows("SELECT status FROM oidc_backchannel_logout_outbox"))[0]["status"] == "failed"
    [dev] = await get_unpaired(app_client)
    assert dev["lockouts"] == [{"app_name": "bc_app", "state": "failed"}]

    r = await app_client.post(f"protected/terminals/unpaired/{tid}/retry")
    assert r.status_code == 204

    # the failed row was reset; the drain the retry triggers re-attempts it, so
    # it is pending again against a running app — no longer failed.
    [dev] = await get_unpaired(app_client)
    assert dev["lockouts"] == [{"app_name": "bc_app", "state": "retrying"}]

    r = await app_client.post("protected/terminals/unpaired/does-not-exist/retry")
    assert r.status_code == 404


async def test_dismiss_removes_the_device_and_releases_the_barrier(app_client: AsyncClient):
    await pair_new_terminal(app_client, name="phone")
    tid = await connected_terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await set_app_status("bc_app", "stopped")
    await run_code_flow(app_client, oidc_client)
    await unpair(app_client, tid)

    await barrier.rebuild_pending_apps()
    assert "bc_app" in barrier._pending_apps

    r = await app_client.delete(f"protected/terminals/unpaired/{tid}")
    assert r.status_code == 204

    assert await rows("SELECT * FROM terminals WHERE id = %s", tid) == []
    assert await rows("SELECT * FROM oidc_backchannel_logout_outbox") == []
    await barrier.rebuild_pending_apps()
    assert "bc_app" not in barrier._pending_apps

    r = await app_client.delete("protected/terminals/unpaired/does-not-exist")
    assert r.status_code == 404


async def test_dismiss_rejects_a_connected_device(app_client: AsyncClient):
    await pair_new_terminal(app_client, name="phone")
    tid = await connected_terminal_id("phone")
    r = await app_client.delete(f"protected/terminals/unpaired/{tid}")
    assert r.status_code == 404


# --- the websocket message fires on each trigger ----------------------------


async def test_unpaired_terminals_update_is_broadcast_on_each_trigger(
    app_client: AsyncClient, mocker
):
    from shard_core.service import websocket

    # keep delivery failing so the device is never reaped mid-test
    mocker.patch(
        "shard_core.service.oidc_backchannel_logout._post_logout_token",
        side_effect=httpx.ConnectError("always fails"),
    )
    spy = mocker.spy(websocket.ws_worker, "broadcast_message")

    def unpaired_broadcasts():
        return [c for c in spy.call_args_list if c.args[0] == "unpaired_terminals_update"]

    await pair_new_terminal(app_client, name="phone")
    tid = await connected_terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await set_app_status("bc_app", "running")
    await run_code_flow(app_client, oidc_client)

    # on unpair
    await unpair(app_client, tid)
    after_unpair = len(unpaired_broadcasts())
    assert after_unpair >= 1
    assert any(d["id"] == tid for d in unpaired_broadcasts()[-1].args[1])

    # on an app status change
    await signals.on_apps_update.send_async()
    after_apps = len(unpaired_broadcasts())
    assert after_apps > after_unpair

    # on retry
    await app_client.post(f"protected/terminals/unpaired/{tid}/retry")
    after_retry = len(unpaired_broadcasts())
    assert after_retry > after_apps

    # on dismiss
    await app_client.delete(f"protected/terminals/unpaired/{tid}")
    after_dismiss = len(unpaired_broadcasts())
    assert after_dismiss > after_retry
    assert unpaired_broadcasts()[-1].args[1] == []
