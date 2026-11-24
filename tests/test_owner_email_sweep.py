"""The startup sweep that catches up on confirmation sends a tokenless
pending_email bypassed.

A tokenless pending_email (pending_email set, email_token_hash NULL) is what
migration 0005's one-time carryover of the old Public-page address leaves on
every shard that upgrades through it, and what a signal handler used to
leave behind before it was fixed to go through set_email() (see
tests/test_owner_email.py and tests/test_terminals.py). These tests seed
that exact shape directly — bypassing set_email(), the same way the
migration does — and run the sweep (owner_email.send_missing_verifications())
directly rather than booting the whole app, since the app_factory hook just
calls it.
"""

import json
from urllib.parse import urlparse

import responses

from shard_core.data_model.user import Role
from shard_core.database import users as db_users
from shard_core.database.connection import db_conn
from shard_core.service import identity, owner_email, user
from shard_core.settings import settings
from tests.conftest import settings_override

VERIFY_PATH = "/api/email_verification"


def controller_url(path: str) -> str:
    return f"{settings().freeshard_controller.base_url}{path}"


def calls_to(requests_mock, path: str) -> list:
    return [c for c in requests_mock.calls if urlparse(c.request.url).path == path]


async def _seed_owner_with_unsent_pending(address: str):
    await identity.init_default_identity()
    owner = await user.ensure_owner_user()
    async with db_conn() as conn:
        await db_users.update(conn, owner.id, {"pending_email": address})
    return owner


async def _seed_member_with_unsent_pending(address: str, username: str):
    async with db_conn() as conn:
        member = await db_users.insert(
            conn,
            {
                "username": username,
                "display_name": username,
                "email": None,
                "role": Role.MEMBER.value,
            },
        )
        await db_users.update(conn, member.id, {"pending_email": address})
    return member


async def _get(user_id):
    async with db_conn() as conn:
        return await db_users.get_by_id(conn, user_id)


async def test_sweep_sends_a_real_verification_for_a_tokenless_candidate(
    requests_mock, db
):
    owner = await _seed_owner_with_unsent_pending("owner@example.org")

    await owner_email.send_missing_verifications()

    requested = json.loads(calls_to(requests_mock, VERIFY_PATH)[0].request.body)
    assert requested["address"] == "owner@example.org"
    assert requested["token"]
    updated = await _get(owner.id)
    assert updated.pending_email == "owner@example.org"
    assert updated.email_token_hash is not None
    assert updated.email_token_expires is not None


async def test_sweep_is_skipped_when_the_shard_cannot_send_mail(requests_mock, db):
    """Same posture as the rest of this module: a self-hosted shard with no
    controller has no mail to catch anyone up on."""
    owner = await _seed_owner_with_unsent_pending("owner@example.org")

    with settings_override({"email": {"enabled": False}}):
        await owner_email.send_missing_verifications()

    assert calls_to(requests_mock, VERIFY_PATH) == []
    updated = await _get(owner.id)
    assert updated.pending_email == "owner@example.org"
    assert updated.email_token_hash is None


async def test_a_failed_send_does_not_stop_the_sweep_from_processing_others(
    requests_mock, db
):
    """A row whose send fails keeps no token, so it is picked up again on the
    next startup; that must not stop the rest of the sweep from running."""
    owner = await _seed_owner_with_unsent_pending("first@example.org")
    member = await _seed_member_with_unsent_pending("second@example.org", "member1")

    calls = {"n": 0}

    def flaky_verify(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return 500, {}, "nope"
        return 201, {}, ""

    requests_mock.replace(
        responses.CallbackResponse(
            method=responses.POST,
            url=controller_url(VERIFY_PATH),
            callback=flaky_verify,
        )
    )

    await owner_email.send_missing_verifications()

    assert calls["n"] == 2
    updated_owner = await _get(owner.id)
    updated_member = await _get(member.id)
    tokens = [updated_owner.email_token_hash, updated_member.email_token_hash]
    # one send failed and must still have no token (retried on the next
    # startup), the other succeeded and must now have one
    assert tokens.count(None) == 1
    assert sum(t is not None for t in tokens) == 1
