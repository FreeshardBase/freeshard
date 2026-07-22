import logging

import responses
from starlette import status

from shard_core.data_model.identity import Identity, OutputIdentity
from shard_core.database import peers as db_peers
from shard_core.database.connection import db_conn
from shard_core.data_model.peer import Peer
from shard_core.service.peer import update_all_peer_pubkeys


def _whoareyou_url(identity: Identity) -> str:
    return f"https://{identity.short_id}.freeshard.cloud/core/public/meta/whoareyou"


async def _insert_peer(identity: Identity, name: str, is_reachable: bool = True):
    async with db_conn() as conn:
        await db_peers.insert(
            conn,
            {
                "id": identity.id,
                "name": name,
                "public_bytes_b64": identity.public_key_pem,
                "is_reachable": is_reachable,
            },
        )


async def _get_peer(identity: Identity) -> Peer:
    async with db_conn() as conn:
        return Peer(**await db_peers.get_by_id_prefix(conn, identity.id))


async def test_unreachable_peer_does_not_block_others(db):
    bad = Identity.create("bad peer")
    good = Identity.create("good peer")
    await _insert_peer(bad, name="stale bad")
    await _insert_peer(good, name="stale good", is_reachable=False)

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.get(_whoareyou_url(bad), status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        rsps.get(
            _whoareyou_url(good),
            json=OutputIdentity(**good.model_dump()).model_dump(),
        )

        await update_all_peer_pubkeys()

        # both peers were really contacted (the 500 path was exercised, not a
        # silent ConnectionError fallback from a mismatched URL)
        assert len(rsps.calls) == 2

    good_peer = await _get_peer(good)
    assert good_peer.name == "good peer"
    assert good_peer.is_reachable is True

    bad_peer = await _get_peer(bad)
    assert bad_peer.is_reachable is False


async def test_unexpected_peer_error_does_not_block_others(db, memory_logger):
    broken = Identity.create("broken peer")
    good = Identity.create("good peer")
    await _insert_peer(broken, name="stale broken")
    await _insert_peer(good, name="stale good", is_reachable=False)

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        # broken peer answers with a different identity than its stored id,
        # which raises inside update_peer_meta and is not caught there
        rsps.get(
            _whoareyou_url(broken),
            json=OutputIdentity(
                **Identity.create("impostor").model_dump()
            ).model_dump(),
        )
        rsps.get(
            _whoareyou_url(good),
            json=OutputIdentity(**good.model_dump()).model_dump(),
        )

        await update_all_peer_pubkeys()

    good_peer = await _get_peer(good)
    assert good_peer.name == "good peer"
    assert good_peer.is_reachable is True

    # the unexpected error is swallowed by the gather and left the broken peer
    # untouched, and it was surfaced via a warning
    broken_peer = await _get_peer(broken)
    assert broken_peer.name == "stale broken"
    assert any(
        r.levelno == logging.WARNING and broken.short_id in r.getMessage()
        for r in memory_logger.records
    )
