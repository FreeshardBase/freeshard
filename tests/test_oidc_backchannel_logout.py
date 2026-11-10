"""Tests for OIDC Back-Channel Logout 1.0 delivery (issue #192).

Follow-up to tests/test_oidc.py's terminal-binding/revocation-on-unpair
coverage: those tests prove the shard's own tokens die on un-pair. These
prove the separate, harder half — that a durable notification gets queued
for the app to kill its own session.

This slice covers enqueue (reading the terminal's live grants and writing
one outbox row per (client_id, sid) BEFORE the un-pair transaction revokes
them / deletes the terminal row), registering a client's logout URI, and
delivery itself: minting a fresh logout_token on every attempt, retrying
with backoff, and the bounded-retry-then-permanently-failed path. Discovery
advertises backchannel_logout_supported unconditionally (covered by
tests/test_oidc.py::test_discovery_document) since the whole /oidc router
already 404s unless oidc.enabled is set — there is no separate flag.

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


async def test_register_client_rejects_a_non_http_scheme_backchannel_logout_uri(
    app_client: AsyncClient,
):
    """Defense-in-depth against SSRF (found in review): backchannel_logout_uri
    is app-declared metadata that ends up as the target of an outbound
    request shard_core itself makes at delivery time, unlike redirect_uris
    (only ever string-compared, never dereferenced). A non-http(s) scheme
    must never reach the database."""
    await ensure_app("evil_app")
    client = await oidc_provider.register_client(
        "evil_app", [REDIRECT_URI], backchannel_logout_uri="javascript:alert(1)"
    )
    assert client.backchannel_logout_uri is None

    async with db_conn() as conn:
        stored = await db_oidc.get_client(conn, client.client_id)
    assert stored.backchannel_logout_uri is None


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


async def test_on_apps_update_signal_drains_a_due_entry(
    app_client: AsyncClient, mocker
):
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
        due = await db_oidc.claim_due_outbox_entries(conn)
    assert due == []


async def test_missing_backchannel_logout_uri_at_delivery_fails_fast(
    app_client: AsyncClient, mocker
):
    """The claim query live-joins oidc_clients rather than snapshotting the
    uri at enqueue time, so a reinstall that drops backchannel_logout_uri
    can null it out from under an already-queued row. There is nowhere to
    deliver to any more -- this must fail immediately, not retry forever
    (found in review: an earlier version had no such guard)."""
    post = mocker.patch("shard_core.service.oidc_backchannel_logout._post_logout_token")
    await pair_new_terminal(app_client, name="phone")
    tid = await terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await set_app_status("bc_app", "running")
    await run_code_flow(app_client, oidc_client)
    await unpair(app_client, tid)

    async with db_conn() as conn:
        await conn.execute(
            "UPDATE oidc_clients SET backchannel_logout_uri = NULL WHERE client_id = %s",
            (oidc_client.client_id,),
        )

    await oidc_backchannel_logout.drain_due_outbox()

    post.assert_not_called()
    final = (await rows("SELECT * FROM oidc_backchannel_logout_outbox"))[0]
    assert final["status"] == "failed"
    assert "backchannel_logout_uri" in final["last_error"]


async def test_non_http_exception_during_post_is_retried_not_stuck(
    app_client: AsyncClient, mocker
):
    """Regression for the bug class found in review: a prior version only
    caught httpx.HTTPError around the POST, so any other exception (e.g. a
    TypeError from a bad argument) escaped to drain_due_outbox's batch-level
    catch-all, which cannot update next_attempt_at/status -- the row stayed
    due and was retried on every single drain forever, uncapped. Any
    exception from the POST must flow through the normal retry bookkeeping."""
    mocker.patch(
        "shard_core.service.oidc_backchannel_logout._post_logout_token",
        side_effect=TypeError("Request URL is missing an 'http://' scheme"),
    )
    await pair_new_terminal(app_client, name="phone")
    tid = await terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await set_app_status("bc_app", "running")
    await run_code_flow(app_client, oidc_client)
    await unpair(app_client, tid)

    await oidc_backchannel_logout.drain_due_outbox()

    entry = (await rows("SELECT * FROM oidc_backchannel_logout_outbox"))[0]
    assert (
        entry["status"] == "pending"
    ), "must be released for retry, not stuck in_flight"
    assert entry["attempts"] == 1
    assert "TypeError" in entry["last_error"]
    assert entry["next_attempt_at"] > entry["created"]


async def test_concurrent_claims_do_not_double_claim_a_row(app_client: AsyncClient):
    """Two overlapping drains (the on_apps_update signal and the periodic
    backstop are independent, uncoordinated callers) must split due rows
    between them, never both deliver to the same one. Uses two genuinely
    separate, overlapping connections -- conn1's claim transaction is still
    open (uncommitted, row lock held) when conn2 attempts its own claim --
    to prove the FOR UPDATE SKIP LOCKED mechanism itself, not just that an
    already-committed status flip is invisible to a later query."""
    await pair_new_terminal(app_client, name="phone")
    tid = await terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await set_app_status("bc_app", "running")
    await run_code_flow(app_client, oidc_client)
    await unpair(app_client, tid)

    async with db_conn() as conn1:
        first_claim = await db_oidc.claim_due_outbox_entries(conn1)
        assert len(first_claim) == 1
        assert first_claim[0]["client_id"] == oidc_client.client_id

        # conn1's transaction has not committed yet -- its FOR UPDATE row
        # lock is still held. A second, independent connection (what a
        # genuinely concurrent drain would use) must not be able to claim
        # the same row while that lock stands.
        async with db_conn() as conn2:
            second_claim = await db_oidc.claim_due_outbox_entries(conn2)
        assert (
            second_claim == []
        ), "SKIP LOCKED must exclude a row locked by another transaction"

    entry = (await rows("SELECT * FROM oidc_backchannel_logout_outbox"))[0]
    assert entry["status"] == "in_flight"


async def test_stuck_in_flight_row_is_reclaimed_after_a_crash(app_client: AsyncClient):
    """A row claimed (flipped to 'in_flight') by a process that then crashed
    before calling mark_outbox_delivered/retry/failed must not be stranded
    forever -- it has to come back to the pool of claimable work once it's
    been stuck long enough to assume the claimant is gone."""
    await pair_new_terminal(app_client, name="phone")
    tid = await terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await set_app_status("bc_app", "running")
    await run_code_flow(app_client, oidc_client)
    await unpair(app_client, tid)

    async with db_conn() as conn:
        claimed = await db_oidc.claim_due_outbox_entries(conn)
    assert len(claimed) == 1
    entry_id = claimed[0]["id"]

    # simulate the claim going stale (process died mid-delivery): backdate
    # `updated` past the stuck threshold instead of waiting it out for real.
    await rows(
        "UPDATE oidc_backchannel_logout_outbox "
        "SET updated = now() - interval '10 minutes' WHERE id = %s RETURNING id",
        entry_id,
    )

    async with db_conn() as conn:
        # threshold well above the 10-minute backdate above -- not a tight
        # boundary, to avoid flaking on wall-clock drift between statements
        not_yet = await db_oidc.claim_due_outbox_entries(conn, stuck_after_seconds=900)
    assert not_yet == [], "must not reclaim before the stuck threshold"

    async with db_conn() as conn:
        reclaimed = await db_oidc.claim_due_outbox_entries(conn, stuck_after_seconds=60)
    assert [r["id"] for r in reclaimed] == [entry_id]


async def test_outcome_writes_are_guarded_against_a_stale_straggler(
    app_client: AsyncClient,
):
    """A row reclaimed from a slow-but-not-crashed worker leaves two writers
    racing to record an outcome for the same id. mark_outbox_delivered/
    retry/failed must only take effect for the writer whose claim is still
    the current one (status='in_flight') -- found in review: without the
    guard, whichever writer runs last silently stomps the other's result,
    including turning an already-'delivered' row back to 'pending'."""
    await pair_new_terminal(app_client, name="phone")
    tid = await terminal_id("phone")
    oidc_client = await make_client("bc_app")
    await set_app_status("bc_app", "running")
    await run_code_flow(app_client, oidc_client)
    await unpair(app_client, tid)
    entry_id = (await rows("SELECT * FROM oidc_backchannel_logout_outbox"))[0]["id"]

    async with db_conn() as conn:
        claimed = await db_oidc.claim_due_outbox_entries(conn)
    assert [c["id"] for c in claimed] == [entry_id]

    # a stale straggler's writes must all be no-ops once the row is no
    # longer 'in_flight' under it (simulated here by marking it delivered
    # out from under the "straggler", rather than engineering a second
    # real claim race)
    async with db_conn() as conn:
        await db_oidc.mark_outbox_delivered(conn, entry_id)
    delivered = (await rows("SELECT * FROM oidc_backchannel_logout_outbox"))[0]
    assert delivered["status"] == "delivered"

    async with db_conn() as conn:
        await db_oidc.mark_outbox_retry(
            conn, entry_id, 1, delivered["next_attempt_at"], "stale straggler"
        )
    unchanged = (await rows("SELECT * FROM oidc_backchannel_logout_outbox"))[0]
    assert unchanged["status"] == "delivered", "stale write must not resurrect the row"
    assert unchanged["last_error"] is None
