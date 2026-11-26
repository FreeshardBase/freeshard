"""The owner's email address: candidate, confirmation, and what it costs.

The invariant under test throughout is that users.email only ever holds an
address somebody proved they can read — that is what the OIDC email_verified
claim rests on (see tests/test_oidc.py for the claim itself).
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import responses
from httpx import AsyncClient

from shard_core.database import preferences as db_preferences
from shard_core.database import users as db_users
from shard_core.database.connection import db_conn
from shard_core.settings import settings
from tests.conftest import settings_override
from tests.util import pair_new_terminal

ME = "protected/users/me"
RESEND = "protected/users/me/email/resend"
PENDING = "protected/users/me/email/pending"
CONFIRM = "public/users/confirm-email"

RELAY_PATH = "/api/email_relay"
VERIFY_PATH = "/api/email_verification"
MIRROR_PATH = "/api/shards/self/owner-email"

NEW_ADDRESS = "owner@example.org"
# what the mocked controller reports as the shard's owner (tests.conftest.mock_shard)
PROFILE_ADDRESS = "testowner@foobar.com"


def controller_url(path: str) -> str:
    return f"{settings().freeshard_controller.base_url}{path}"


def calls_to(requests_mock, path: str) -> list:
    return [c for c in requests_mock.calls if urlparse(c.request.url).path == path]


def call_order(requests_mock, *paths: str) -> list[str]:
    seen = [urlparse(c.request.url).path for c in requests_mock.calls]
    return [p for p in seen if p in paths]


async def get_owner():
    async with db_conn() as conn:
        return await db_users.get_owner(conn)


async def set_address(client: AsyncClient, address=NEW_ADDRESS):
    response = await client.patch(ME, json={"email": address})
    assert response.status_code == 200, response.text
    return response.json()


async def set_confirmed_email_directly(address: str):
    """Seed an already-verified address, bypassing set/confirm, for tests whose
    precondition is a genuine previous address rather than a fresh shard's
    default None (see the 0005-migration invariant in owner_email.py)."""
    async with db_conn() as conn:
        await db_users.update(conn, (await get_owner()).id, {"email": address})


def sent_token(requests_mock) -> str:
    calls = calls_to(requests_mock, VERIFY_PATH)
    assert calls, "no verification email was requested"
    return json.loads(calls[-1].request.body)["token"]


# --- reading the user ------------------------------------------------------------


async def test_me_returns_the_owner(requests_mock, app_client: AsyncClient):
    await pair_new_terminal(app_client)

    response = await app_client.get(ME)

    assert response.status_code == 200
    body = response.json()
    owner = await get_owner()
    assert body["id"] == owner.id
    assert body["username"] == "owner"
    assert body["role"] == "owner"
    # a fresh shard has confirmed nothing, so there is no verified address
    assert body["email"] is None


async def test_me_without_a_session_is_rejected(app_client: AsyncClient):
    assert (await app_client.get(ME)).status_code == 401
    assert (await app_client.patch(ME, json={})).status_code == 401
    assert (await app_client.post(RESEND)).status_code == 401
    assert (await app_client.delete(PENDING)).status_code == 401


async def test_me_hides_the_confirmation_token(requests_mock, app_client: AsyncClient):
    await pair_new_terminal(app_client)
    await set_address(app_client)

    body = (await app_client.get(ME)).json()

    assert (await get_owner()).email_token_hash is not None
    assert "email_token_hash" not in body
    assert "email_token_expires" not in body


async def test_me_exposes_whether_the_pending_candidate_was_ever_sent(
    requests_mock, app_client: AsyncClient
):
    """pending_email_sent is what a UI needs to word its action correctly: a
    candidate nobody ever attempted to deliver (migration 0005's carryover,
    or a failed enrichment falling back to a raw write) must not be offered
    as a "resend" — nothing has gone out to resend."""
    await pair_new_terminal(app_client)
    # pairing already seeded a real, sent candidate via the controller profile
    assert (await app_client.get(ME)).json()["pending_email_sent"] is True

    owner = await get_owner()
    async with db_conn() as conn:
        await db_users.update(
            conn,
            owner.id,
            {
                "pending_email": PROFILE_ADDRESS,
                "email_token_hash": None,
                "email_token_expires": None,
            },
        )
    assert (await app_client.get(ME)).json()["pending_email_sent"] is False


async def test_pairing_seeds_the_controller_address_as_a_candidate(
    requests_mock, app_client: AsyncClient
):
    """The controller's signup address was never verified either, and pairing
    sends it through the real verification flow like any other candidate."""
    await pair_new_terminal(app_client)

    owner = await get_owner()
    assert owner.email is None
    assert owner.pending_email == PROFILE_ADDRESS
    assert owner.email_token_hash is not None

    await app_client.post(CONFIRM, json={"token": sent_token(requests_mock)})
    assert (await get_owner()).email == PROFILE_ADDRESS


# --- setting an address ----------------------------------------------------------


async def test_setting_an_address_writes_a_candidate_and_sends_a_link(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)

    body = await set_address(app_client)

    assert body["email"] is None, "the address must not count as verified yet"
    assert body["pending_email"] == NEW_ADDRESS
    owner = await get_owner()
    assert owner.email is None
    assert owner.pending_email == NEW_ADDRESS

    # [-1]: pairing already sent one verification, for the controller's
    # signup address candidate (see test_pairing_seeds_the_controller_...)
    requested = json.loads(calls_to(requests_mock, VERIFY_PATH)[-1].request.body)
    assert requested["address"] == NEW_ADDRESS
    assert requested["token"]
    assert requested["language"] is None, "a fresh owner has no stored language preference"


async def test_setting_an_address_passes_the_owners_stored_language(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)
    owner = await get_owner()
    async with db_conn() as conn:
        await db_preferences.put(conn, owner.id, {"language": "de"})

    await set_address(app_client)

    requested = json.loads(calls_to(requests_mock, VERIFY_PATH)[0].request.body)
    assert requested["language"] == "de"


async def test_resending_also_passes_the_owners_stored_language(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)
    await set_address(app_client)
    owner = await get_owner()
    async with db_conn() as conn:
        await db_preferences.put(conn, owner.id, {"language": "de"})

    response = await app_client.post(RESEND)
    assert response.status_code == 204, response.text

    requested = json.loads(calls_to(requests_mock, VERIFY_PATH)[-1].request.body)
    assert requested["language"] == "de"


async def test_the_token_is_stored_only_as_a_digest(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)
    await set_address(app_client)
    token = sent_token(requests_mock)

    owner = await get_owner()

    assert owner.email_token_hash == hashlib.sha256(token.encode()).hexdigest()
    async with db_conn() as conn:
        cur = await conn.execute(
            "SELECT count(*) FROM users WHERE email_token_hash = %s", (token,)
        )
        assert (await cur.fetchone())[0] == 0


async def test_setting_a_second_address_replaces_the_first_candidate(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)
    await set_address(app_client, "first@example.org")
    first_token = sent_token(requests_mock)

    await set_address(app_client, "second@example.org")

    owner = await get_owner()
    assert owner.pending_email == "second@example.org"
    r = await app_client.post(CONFIRM, json={"token": first_token})
    assert r.status_code == 204
    assert (await get_owner()).email is None, "the superseded token still worked"


async def test_an_invalid_address_is_rejected(requests_mock, app_client: AsyncClient):
    await pair_new_terminal(app_client)
    calls_before = len(calls_to(requests_mock, VERIFY_PATH))

    response = await app_client.patch(ME, json={"email": "i am invalid"})

    assert response.status_code == 422
    assert len(calls_to(requests_mock, VERIFY_PATH)) == calls_before


async def test_an_empty_address_is_rejected_rather_than_treated_as_a_clear(
    requests_mock, app_client: AsyncClient
):
    """A form that blanks its field sends "", not null. Routing that to the
    clear path would wipe the controller's copy — the only way we reach a paying
    customer — on what the user meant as a correction."""
    await pair_new_terminal(app_client)

    response = await app_client.patch(ME, json={"email": ""})

    assert response.status_code == 422
    assert calls_to(requests_mock, RELAY_PATH) == []
    assert calls_to(requests_mock, MIRROR_PATH) == []


async def test_the_address_is_stored_normalized(requests_mock, app_client: AsyncClient):
    """It is asserted as verified to third parties, so the domain casing must
    not be whatever the owner happened to type."""
    await pair_new_terminal(app_client)

    body = await set_address(app_client, "Owner@EXAMPLE.ORG")

    assert body["pending_email"] == "Owner@example.org"


async def test_omitting_the_address_leaves_it_untouched(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)
    await set_address(app_client)
    calls_before = len(calls_to(requests_mock, VERIFY_PATH))

    response = await app_client.patch(ME, json={"display_name": "Renamed"})

    assert response.status_code == 200
    assert response.json()["display_name"] == "Renamed"
    assert response.json()["pending_email"] == NEW_ADDRESS
    assert len(calls_to(requests_mock, VERIFY_PATH)) == calls_before


async def test_a_failed_delivery_reports_an_error_and_keeps_the_candidate(
    requests_mock, app_client: AsyncClient
):
    """Resend is the recovery, so the candidate has to survive the failure."""
    await pair_new_terminal(app_client)
    requests_mock.replace(
        responses.POST, controller_url(VERIFY_PATH), status=500, body="nope"
    )

    response = await app_client.patch(ME, json={"email": NEW_ADDRESS})

    assert response.status_code == 502
    owner = await get_owner()
    assert owner.pending_email == NEW_ADDRESS
    assert owner.email is None


async def test_a_member_cannot_touch_the_owners_address(
    requests_mock, app_client: AsyncClient
):
    """The relay mails the shard's owner and the mirror rewrites the owner's
    address on the controller, whoever asked."""
    await pair_new_terminal(app_client)
    async with db_conn() as conn:
        await db_users.update(conn, (await get_owner()).id, {"role": "member"})

    assert (await app_client.patch(ME, json={"email": NEW_ADDRESS})).status_code == 403
    assert (await app_client.post(RESEND)).status_code == 403
    assert (await app_client.delete(PENDING)).status_code == 403
    # a member may still rename themselves
    assert (await app_client.patch(ME, json={"display_name": "M"})).status_code == 200


async def test_a_disabled_user_is_forbidden(requests_mock, app_client: AsyncClient):
    await pair_new_terminal(app_client)
    async with db_conn() as conn:
        await db_users.update(conn, (await get_owner()).id, {"disabled": True})

    assert (await app_client.get(ME)).status_code == 403


# --- confirming ------------------------------------------------------------------


async def test_confirming_promotes_the_candidate(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)
    await set_address(app_client)
    token = sent_token(requests_mock)

    response = await app_client.post(CONFIRM, json={"token": token})

    assert response.status_code == 204
    owner = await get_owner()
    assert owner.email == NEW_ADDRESS
    assert owner.pending_email is None
    assert owner.email_token_hash is None
    assert owner.email_token_expires is None


async def test_the_old_address_is_told_before_the_switch_is_mirrored(
    requests_mock, app_client: AsyncClient
):
    """The relay only ever reaches the address the controller currently holds,
    so a notification after the mirror would go to the new address. This is a
    genuine change (a prior confirmed address exists) — see the first-
    confirmation test below for why that precondition matters here."""
    await pair_new_terminal(app_client)
    await set_confirmed_email_directly("old@example.org")
    await set_address(app_client)
    token = sent_token(requests_mock)

    await app_client.post(CONFIRM, json={"token": token})

    assert call_order(requests_mock, RELAY_PATH, MIRROR_PATH) == [
        RELAY_PATH,
        MIRROR_PATH,
        RELAY_PATH,
    ]
    assert json.loads(calls_to(requests_mock, MIRROR_PATH)[0].request.body) == {
        "address": NEW_ADDRESS
    }


async def test_a_first_confirmation_does_not_warn_about_a_change(
    requests_mock, app_client: AsyncClient
):
    """A fresh shard's owner has no prior address to warn away from (the
    0005-migration invariant: every shard starts with email = None). Sending
    the "this is changing" notice anyway duplicates the "confirmed" one that
    follows it, usually to the very same inbox — the owner only ever verifies
    one address, the one they gave at signup."""
    await pair_new_terminal(app_client)
    assert (await get_owner()).email is None
    await set_address(app_client)
    token = sent_token(requests_mock)

    await app_client.post(CONFIRM, json={"token": token})

    assert len(calls_to(requests_mock, RELAY_PATH)) == 1
    body = json.loads(calls_to(requests_mock, RELAY_PATH)[0].request.body)
    assert body["subject"] == "Your Freeshard contact address is confirmed"


async def test_confirming_survives_a_controller_that_cannot_send_mail(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)
    await set_address(app_client)
    token = sent_token(requests_mock)
    requests_mock.replace(
        responses.POST, controller_url(RELAY_PATH), status=422, body="no owner_email"
    )

    response = await app_client.post(CONFIRM, json={"token": token})

    assert response.status_code == 204
    assert (await get_owner()).email == NEW_ADDRESS


async def test_confirming_survives_a_controller_that_cannot_mirror(
    requests_mock, app_client: AsyncClient
):
    """The shard owns the address; a failed mirror must not undo a confirmation
    the owner already completed — but it must suppress the success mail, which
    the relay would otherwise send to the address we just abandoned. Needs a
    genuine prior address, or there is no "changing" notice to count here."""
    await pair_new_terminal(app_client)
    await set_confirmed_email_directly("old@example.org")
    await set_address(app_client)
    token = sent_token(requests_mock)
    requests_mock.replace(
        responses.PUT, controller_url(MIRROR_PATH), status=500, body="nope"
    )

    response = await app_client.post(CONFIRM, json={"token": token})

    assert response.status_code == 204
    assert (await get_owner()).email == NEW_ADDRESS
    assert len(calls_to(requests_mock, RELAY_PATH)) == 1


async def test_a_candidate_set_while_a_link_was_in_flight_survives(
    requests_mock, app_client: AsyncClient
):
    """The confirmation promotes the address its own link was sent to, or
    nothing — it must never clear a candidate it knows nothing about."""
    await pair_new_terminal(app_client)
    await set_address(app_client, "first@example.org")
    stale_token = sent_token(requests_mock)
    await set_address(app_client, "second@example.org")
    fresh_token = sent_token(requests_mock)

    assert (
        await app_client.post(CONFIRM, json={"token": stale_token})
    ).status_code == 204

    owner = await get_owner()
    assert owner.email is None
    assert owner.pending_email == "second@example.org"
    await app_client.post(CONFIRM, json={"token": fresh_token})
    assert (await get_owner()).email == "second@example.org"


async def test_an_unknown_token_changes_nothing_and_says_nothing(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)
    await set_address(app_client)

    response = await app_client.post(CONFIRM, json={"token": "not-the-token"})

    assert response.status_code == 204, "a miss must look exactly like a hit"
    owner = await get_owner()
    assert owner.email is None
    assert owner.pending_email == NEW_ADDRESS


async def test_an_expired_token_does_not_promote(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)
    await set_address(app_client)
    token = sent_token(requests_mock)
    owner = await get_owner()
    async with db_conn() as conn:
        await db_users.update(
            conn,
            owner.id,
            {"email_token_expires": datetime.now(timezone.utc) - timedelta(minutes=1)},
        )

    response = await app_client.post(CONFIRM, json={"token": token})

    assert response.status_code == 204
    assert (await get_owner()).email is None


async def test_a_token_works_only_once(requests_mock, app_client: AsyncClient):
    await pair_new_terminal(app_client)
    await set_address(app_client)
    token = sent_token(requests_mock)
    await app_client.post(CONFIRM, json={"token": token})
    async with db_conn() as conn:
        await db_users.update(
            conn, (await get_owner()).id, {"pending_email": "attacker@example.org"}
        )

    response = await app_client.post(CONFIRM, json={"token": token})

    assert response.status_code == 204
    assert (await get_owner()).email == NEW_ADDRESS


async def test_a_malformed_token_is_refused(requests_mock, app_client: AsyncClient):
    assert (await app_client.post(CONFIRM, json={"token": ""})).status_code == 422
    assert (
        await app_client.post(CONFIRM, json={"token": "x" * 513})
    ).status_code == 422
    assert (await app_client.post(CONFIRM, json={})).status_code == 422


async def test_there_is_no_get_confirmation_route(app_client: AsyncClient):
    """A GET would be consumed by mail scanners and link prefetchers, burning
    the single-use token before the owner ever clicked."""
    assert (await app_client.get(f"{CONFIRM}?token=whatever")).status_code == 405


async def test_a_flood_of_guesses_cannot_lock_the_owner_out(
    requests_mock, app_client: AsyncClient
):
    """Only misses are charged. A global limiter that counted hits too would let
    any anonymous caller keep the owner off the one route that verifies an
    address, until the token expired."""
    await pair_new_terminal(app_client)
    await set_address(app_client)
    token = sent_token(requests_mock)
    for _ in range(20):
        assert (
            await app_client.post(CONFIRM, json={"token": "guess"})
        ).status_code == 204
    assert (await app_client.post(CONFIRM, json={"token": "guess"})).status_code == 429

    assert (await app_client.post(CONFIRM, json={"token": token})).status_code == 204
    assert (await get_owner()).email == NEW_ADDRESS


# --- resending and discarding ----------------------------------------------------


async def test_resending_replaces_the_token(requests_mock, app_client: AsyncClient):
    await pair_new_terminal(app_client)
    await set_address(app_client)
    first_token = sent_token(requests_mock)

    response = await app_client.post(RESEND)

    assert response.status_code == 204
    second_token = sent_token(requests_mock)
    assert second_token != first_token
    r = await app_client.post(CONFIRM, json={"token": first_token})
    assert r.status_code == 204
    assert (await get_owner()).email is None, "the replaced token still worked"
    await app_client.post(CONFIRM, json={"token": second_token})
    assert (await get_owner()).email == NEW_ADDRESS


async def test_resending_without_a_candidate_is_refused(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)
    await app_client.delete(PENDING)
    calls_before = len(calls_to(requests_mock, VERIFY_PATH))

    response = await app_client.post(RESEND)

    assert response.status_code == 409
    assert len(calls_to(requests_mock, VERIFY_PATH)) == calls_before


async def test_sending_confirmation_mail_is_rate_limited(
    requests_mock, app_client: AsyncClient
):
    """Setting an address and resending share one budget, so alternating
    between the two routes cannot double the mail a shard can send. Pairing
    itself spends one unit of that budget too, now that it sends a real
    verification for the controller's signup address candidate."""
    await pair_new_terminal(app_client)
    await set_address(app_client)
    for _ in range(3):
        assert (await app_client.post(RESEND)).status_code == 204

    assert (await app_client.post(RESEND)).status_code == 429
    assert (await app_client.patch(ME, json={"email": NEW_ADDRESS})).status_code == 429


async def test_resending_mints_a_token_for_a_candidate_seeded_without_one(
    requests_mock, app_client: AsyncClient
):
    """Where every shard that has been through the 0005 migration starts: a
    candidate with no token, written directly rather than through
    set_email(). There is no automatic catch-up for this — resend is the
    only recovery, and it must work from this exact seeded shape."""
    await pair_new_terminal(app_client)
    owner = await get_owner()
    async with db_conn() as conn:
        await db_users.update(
            conn,
            owner.id,
            {
                "pending_email": PROFILE_ADDRESS,
                "email_token_hash": None,
                "email_token_expires": None,
            },
        )
    owner = await get_owner()
    assert (owner.pending_email, owner.email_token_hash) == (PROFILE_ADDRESS, None)

    assert (await app_client.post(RESEND)).status_code == 204

    await app_client.post(CONFIRM, json={"token": sent_token(requests_mock)})
    assert (await get_owner()).email == PROFILE_ADDRESS


async def test_discarding_the_candidate_drops_its_token(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)
    await set_address(app_client)
    token = sent_token(requests_mock)

    response = await app_client.delete(PENDING)

    assert response.status_code == 204
    owner = await get_owner()
    assert owner.pending_email is None
    assert owner.email_token_hash is None
    await app_client.post(CONFIRM, json={"token": token})
    assert (await get_owner()).email is None


# --- clearing --------------------------------------------------------------------


async def test_clearing_tells_the_old_address_first(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)
    await set_address(app_client)
    await app_client.post(CONFIRM, json={"token": sent_token(requests_mock)})

    response = await app_client.patch(ME, json={"email": None})

    assert response.status_code == 200
    assert response.json()["email"] is None
    owner = await get_owner()
    assert owner.email is None
    assert owner.pending_email is None
    assert call_order(requests_mock, RELAY_PATH, MIRROR_PATH)[-2:] == [
        RELAY_PATH,
        MIRROR_PATH,
    ]
    assert json.loads(calls_to(requests_mock, MIRROR_PATH)[-1].request.body) == {
        "address": None
    }


# --- self-hosted, where no mail can be sent --------------------------------------
#
# A shard reaching enrich_identity_from_profile has, by definition, a
# reachable controller (profile.owner_email came from it) — and every
# managed shard has mail enabled. email.enabled=False is the self-hosted
# marker, and a self-hosted shard has no controller to have gotten this far
# with, so that combination cannot occur on the pairing path. Coverage below
# is for the PATCH /me path instead, where an owner's own self-hosted shard
# really does take this branch.


async def test_without_verification_the_address_is_set_directly(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)
    calls_before = len(calls_to(requests_mock, VERIFY_PATH))

    with settings_override({"email": {"enabled": False}}):
        body = await set_address(app_client)

    assert body["email"] == NEW_ADDRESS
    assert body["pending_email"] is None
    owner = await get_owner()
    assert owner.email == NEW_ADDRESS
    assert owner.email_token_hash is None
    assert len(calls_to(requests_mock, VERIFY_PATH)) == calls_before
    assert json.loads(calls_to(requests_mock, MIRROR_PATH)[0].request.body) == {
        "address": NEW_ADDRESS
    }


async def test_clearing_an_address_that_is_already_empty_does_nothing(
    requests_mock, app_client: AsyncClient
):
    """Where every shard sits right after the 0005 migration, while the
    controller still holds the signup address. Mirroring a null there is what
    silently stops disk, billing and wind-down mail to a paying customer."""
    await pair_new_terminal(app_client)
    await app_client.delete(PENDING)

    response = await app_client.patch(ME, json={"email": None})

    assert response.status_code == 200
    assert calls_to(requests_mock, RELAY_PATH) == []
    assert calls_to(requests_mock, MIRROR_PATH) == []


async def test_without_verification_resending_is_refused(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)
    calls_before = len(calls_to(requests_mock, VERIFY_PATH))

    with settings_override({"email": {"enabled": False}}):
        response = await app_client.post(RESEND)

    assert response.status_code == 409
    assert len(calls_to(requests_mock, VERIFY_PATH)) == calls_before


async def test_without_verification_the_send_budget_is_not_spent(
    requests_mock, app_client: AsyncClient
):
    """A shard that cannot send mail at all has nothing to ration."""
    with settings_override({"email": {"enabled": False}}):
        await pair_new_terminal(app_client)
        for i in range(8):
            assert (await set_address(app_client, f"a{i}@example.org"))[
                "email"
            ] == f"a{i}@example.org"


async def test_without_verification_clearing_sends_no_notification(
    requests_mock, app_client: AsyncClient
):
    await pair_new_terminal(app_client)

    with settings_override({"email": {"enabled": False}}):
        await set_address(app_client)
        response = await app_client.patch(ME, json={"email": None})

    assert response.status_code == 200
    assert (await get_owner()).email is None
    assert calls_to(requests_mock, RELAY_PATH) == []
