"""Tests for the fail-closed back-channel logout barrier.

The barrier (service/oidc_backchannel_barrier.py) holds HTTP traffic to an
app while it still owes an OIDC back-channel logout, so an un-paired device
is never served ahead of its own logout. These prove the four behaviours the
issue pins down: the request path does no work for an app with nothing
pending, traffic is held with a 503 while a logout is undelivered, it is
released the moment delivery drains the queue, and a wedged logout endpoint
fails OPEN after a bounded wait rather than stranding the app forever.

Like tests/test_oidc_backchannel_logout.py these use app_client (no Docker):
nothing here needs a real container, only the outbox rows and the in-process
barrier state.
"""

import asyncio
import time

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from psycopg.rows import dict_row
from starlette import status

from shard_core.database.connection import db_conn
from shard_core.database import oidc as db_oidc
from shard_core.database import terminals as db_terminals
from shard_core.service import (
    oidc_backchannel_barrier as barrier,
    oidc_provider,
)
from shard_core.util import signals
from tests.util import pair_new_terminal, install_app

LOGOUT_URI = "https://bc_app.example/backchannel-logout"
REDIRECT_URI = "https://bc_app.example/oauth/callback"


@pytest.fixture(autouse=True)
def _reset_barrier_state():
    """The barrier's sets are module globals and leak between tests otherwise."""
    for state in (barrier._pending_apps, barrier._locks, barrier._hold_since, barrier._failed_open):
        state.clear()
    yield


async def rows(sql: str, *args) -> list[dict]:
    async with db_conn() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, args)
            return await cur.fetchall()


async def ensure_app(name: str, status_: str = "stopped"):
    async with db_conn() as conn:
        await conn.execute(
            "INSERT INTO installed_apps (name, status) VALUES (%s, %s) "
            "ON CONFLICT (name) DO UPDATE SET status = EXCLUDED.status",
            (name, status_),
        )


async def set_app_status(name: str, status_: str):
    async with db_conn() as conn:
        await conn.execute(
            "UPDATE installed_apps SET status = %s WHERE name = %s", (status_, name)
        )


async def make_client(app_name: str, backchannel_logout_uri: str | None = LOGOUT_URI):
    await ensure_app(app_name)
    return await oidc_provider.register_client(
        app_name, [REDIRECT_URI], backchannel_logout_uri=backchannel_logout_uri
    )


async def enqueue_one(client_id: str, *, sid: str = "sid-1", user_sub: int = 1):
    async with db_conn() as conn:
        await db_oidc.enqueue_backchannel_logout(
            conn, "terminal-x", [{"client_id": client_id, "sid": sid, "user_sub": user_sub}]
        )


async def make_app_with_pending_logout(app_name: str, *, app_status: str = "stopped"):
    """App + registered OIDC client + one pending outbox row, with the barrier
    set rebuilt to reflect it."""
    client = await make_client(app_name)
    await set_app_status(app_name, app_status)
    await enqueue_one(client.client_id)
    await barrier.rebuild_pending_apps()
    return client


# --- the hot path does nothing when nothing is pending ----------------------


async def test_enforce_passes_through_when_no_logout_is_pending(app_client: AsyncClient):
    # No raise, and no state touched: an app with an empty pending set is a
    # plain membership miss — the #89 promise that the empty hot path does no
    # work (no hold timer, no lock, no DB).
    await barrier.enforce("some_app")
    assert "some_app" not in barrier._hold_since
    assert "some_app" not in barrier._locks


# --- hold while undelivered, with the load-bearing 503 ----------------------


async def test_barrier_holds_with_503_while_logout_is_undelivered(
    app_client: AsyncClient, mocker
):
    post = mocker.patch("shard_core.service.oidc_backchannel_logout._post_logout_token")
    await make_app_with_pending_logout("bc_app", app_status="stopped")

    with pytest.raises(HTTPException) as exc_info:
        await barrier.enforce("bc_app")

    # 503 specifically: app_error maps it to the auto-reloading splash, while
    # a 401 would strand the user on an "Access Denied" dead end.
    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    # A stopped app is never woken by the drain just to receive its logout.
    post.assert_not_called()
    assert "bc_app" in barrier._pending_apps


# --- release the moment delivery drains -------------------------------------


async def test_barrier_releases_once_the_logout_is_delivered(
    app_client: AsyncClient, mocker
):
    post = mocker.patch(
        "shard_core.service.oidc_backchannel_logout._post_logout_token",
        return_value=None,
    )
    await make_app_with_pending_logout("bc_app", app_status="running")

    # No raise: the running app receives its logout during the drain the
    # barrier drives, the drain's signal clears the set, and the request falls
    # through.
    await barrier.enforce("bc_app")

    post.assert_called_once()
    assert "bc_app" not in barrier._pending_apps
    entry = (await rows("SELECT * FROM oidc_backchannel_logout_outbox"))[0]
    assert entry["status"] == "delivered"


# --- single-flight ----------------------------------------------------------


async def test_concurrent_requests_drive_a_single_delivery(
    app_client: AsyncClient, mocker
):
    calls = 0

    async def slow_success(url, token):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)

    mocker.patch(
        "shard_core.service.oidc_backchannel_logout._post_logout_token",
        side_effect=slow_success,
    )
    await make_app_with_pending_logout("bc_app", app_status="running")

    # Ten simultaneous requests to a waking app must share one delivery, not
    # fire ten POSTs at the relying party.
    await asyncio.gather(*(barrier.enforce("bc_app") for _ in range(10)))

    assert calls == 1
    assert "bc_app" not in barrier._pending_apps


# --- the request path only drives its own app's delivery --------------------


async def test_enforce_does_not_deliver_another_apps_logout(
    app_client: AsyncClient, mocker
):
    posted: list[str] = []

    async def record(url, token):
        posted.append(url)

    mocker.patch(
        "shard_core.service.oidc_backchannel_logout._post_logout_token",
        side_effect=record,
    )
    await make_app_with_pending_logout("bc_app", app_status="running")
    other = await make_client("other_app", backchannel_logout_uri="https://other.example/blco")
    await set_app_status("other_app", "running")
    await enqueue_one(other.client_id)
    await barrier.rebuild_pending_apps()

    # A request to bc_app must not pay to deliver other_app's logout on the
    # auth hot path, even though it is due and other_app is running.
    await barrier.enforce("bc_app")

    assert posted == [LOGOUT_URI]
    assert "other_app" in barrier._pending_apps
    other_row = (
        await rows(
            "SELECT status FROM oidc_backchannel_logout_outbox WHERE client_id = %s",
            other.client_id,
        )
    )[0]
    assert other_row["status"] == "pending"


# --- fail open after the bounded wait ---------------------------------------


async def test_barrier_fails_open_after_the_deadline(app_client: AsyncClient, mocker):
    post = mocker.patch("shard_core.service.oidc_backchannel_logout._post_logout_token")
    await make_app_with_pending_logout("bc_app", app_status="running")
    # Pretend this app has been held past the fail-open deadline already.
    barrier._hold_since["bc_app"] = time.monotonic() - (barrier.BARRIER_TIMEOUT_SECONDS + 1)

    # No raise: a wedged logout must not brick the app for everyone forever.
    await barrier.enforce("bc_app")

    # Failing open skips delivery entirely and serves the request.
    post.assert_not_called()
    assert "bc_app" in barrier._failed_open


# --- rebuilding the set from the outbox -------------------------------------


@pytest.mark.parametrize(
    "status_, owes",
    [
        ("pending", True),  # waiting for a delivery attempt
        ("in_flight", True),  # claimed, mid-delivery — still owes until it lands
        ("delivered", False),  # done
        ("failed", False),  # retries exhausted; the barrier gives up, not holds
    ],
)
async def test_rebuild_membership_follows_outbox_status(
    app_client: AsyncClient, status_: str, owes: bool
):
    client = await make_client("bc_app")
    await enqueue_one(client.client_id)
    await rows(
        "UPDATE oidc_backchannel_logout_outbox SET status = %s "
        "WHERE client_id = %s RETURNING id",
        status_,
        client.client_id,
    )

    barrier._pending_apps.clear()
    await barrier.rebuild_pending_apps()

    assert ("bc_app" in barrier._pending_apps) is owes


async def test_rebuild_clears_stale_hold_and_fail_open_markers(app_client: AsyncClient):
    client = await make_client("bc_app")
    await enqueue_one(client.client_id)
    await barrier.rebuild_pending_apps()
    barrier._hold_since["bc_app"] = time.monotonic()
    barrier._failed_open.add("bc_app")

    await rows(
        "UPDATE oidc_backchannel_logout_outbox SET status = 'delivered' "
        "WHERE client_id = %s RETURNING id",
        client.client_id,
    )
    await barrier.rebuild_pending_apps()

    assert "bc_app" not in barrier._hold_since
    assert "bc_app" not in barrier._failed_open


# --- wiring: an un-pair populates the set via the signal ---------------------


async def test_unpair_populates_the_pending_set(app_client: AsyncClient):
    await pair_new_terminal(app_client, name="phone")
    async with db_conn() as conn:
        tid = (await db_terminals.get_by_name(conn, "phone"))["id"]
    oidc_client = await make_client("bc_app")
    await _grant_token(oidc_client.client_id, terminal_id=tid)

    assert "bc_app" not in barrier._pending_apps
    r = await app_client.delete(f"protected/terminals/id/{tid}")
    assert r.status_code == 204, r.text

    # delete_terminal_by_id enqueues the logout and fires
    # on_backchannel_outbox_update, which rebuilds the set.
    assert "bc_app" in barrier._pending_apps


async def _grant_token(client_id: str, *, terminal_id: str, sid: str = "sid-1"):
    """Insert one live OIDC token bound to a terminal — the grant an un-pair
    reads to decide what to enqueue."""
    async with db_conn() as conn:
        cur = await conn.execute("SELECT id FROM users LIMIT 1")
        user_sub = (await cur.fetchone())[0]
        await db_oidc.insert_token(
            conn,
            {
                "access_token_hash": f"ah-{sid}",
                "refresh_token_hash": f"rh-{sid}",
                "client_id": client_id,
                "user_sub": user_sub,
                "terminal_id": terminal_id,
                "sid": sid,
                "scope": "openid",
                "issued_at": int(time.time()),
                "expires_in": 3600,
            },
        )


# --- end-to-end through the real forwardAuth endpoint -----------------------


async def test_forward_auth_holds_then_releases(api_client: AsyncClient, mocker):
    """The wire-up: /internal/auth itself must answer 503 while a logout is
    undelivered and 200 once it drains. api_client because the endpoint needs
    the app's metadata on disk (path matching) and a real installed_apps row.
    """
    post = mocker.patch(
        "shard_core.service.oidc_backchannel_logout._post_logout_token",
        return_value=None,
    )
    # Keep the wake a no-op so the app stays stopped and the test stays
    # deterministic — we flip the status by hand to drive delivery.
    mocker.patch(
        "shard_core.service.app_lifecycle.start_app",
        new=mocker.AsyncMock(return_value=None),
    )
    await install_app(api_client, "mock_app")

    client = await oidc_provider.register_client(
        "mock_app", [REDIRECT_URI], backchannel_logout_uri=LOGOUT_URI
    )
    async with db_conn() as conn:
        cur = await conn.execute("SELECT id FROM users LIMIT 1")
        user_sub = (await cur.fetchone())[0]
        await db_oidc.enqueue_backchannel_logout(
            conn, "terminal-x", [{"client_id": client.client_id, "sid": "sid-1", "user_sub": user_sub}]
        )
    await signals.on_backchannel_outbox_update.send_async()

    held = await api_client.get(
        "internal/auth",
        headers={"X-Forwarded-Host": "mock_app.myshard.org", "X-Forwarded-Uri": "/pub"},
    )
    assert held.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    post.assert_not_called()

    await set_app_status("mock_app", "running")
    released = await api_client.get(
        "internal/auth",
        headers={"X-Forwarded-Host": "mock_app.myshard.org", "X-Forwarded-Uri": "/pub"},
    )
    assert released.status_code == status.HTTP_200_OK
    post.assert_called_once()
