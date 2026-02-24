import asyncio
import logging

import httpx
import requests
from fastapi.requests import Request
from http_message_signatures import HTTPSignatureKeyResolver, algorithms
from requests_http_signature import HTTPSignatureAuth

from shard_core.database.connection import db_conn
from shard_core.database import peers as peers_db
from shard_core.data_model.identity import OutputIdentity
from shard_core.data_model.peer import Peer
from shard_core.service.crypto import PublicKey
from shard_core.util import signals

log = logging.getLogger(__name__)


async def get_peer_by_id(id: str):
    async with db_conn() as conn:
        p = await peers_db.get_by_id_prefix(conn, id)
        if p:
            return Peer(**p)
        else:
            raise KeyError(id)


async def update_all_peer_pubkeys():
    async with db_conn() as conn:
        all_peers = await peers_db.get_all(conn)
    peers_with_pubkey = [Peer(**p) for p in all_peers if p.get("public_bytes_b64")]
    await asyncio.gather(*[update_peer_meta(peer) for peer in peers_with_pubkey])


async def update_peer_meta(peer: Peer):
    url = f"https://{peer.short_id}.freeshard.cloud/core/public/meta/whoareyou"

    def do_request():
        return requests.get(url=url)

    try:
        response = await asyncio.get_running_loop().run_in_executor(None, do_request)
    except requests.ConnectionError as e:
        log.debug(f"Could not find peer {peer.short_id}: {e}")
        async with db_conn() as conn:
            await peers_db.update_by_id(conn, peer.id, {"is_reachable": False})
        return

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        log.debug(f"Could not update peer meta for {peer.short_id}: {e}")
        async with db_conn() as conn:
            await peers_db.update_by_id(conn, peer.id, {"is_reachable": False})
        return

    peer_identity = OutputIdentity(**response.json())

    if not peer_identity.id.startswith(peer.id):
        raise KeyError(
            f"Portal {peer.short_id} responded with wrong identity {peer_identity.id}"
        )

    updated_peer = output_identity_to_peer(peer_identity)
    async with db_conn() as conn:
        await peers_db.update_by_id(conn, peer.id, updated_peer.dict())


def output_identity_to_peer(identity: OutputIdentity) -> Peer:
    pubkey = PublicKey(identity.public_key_pem)
    return Peer(
        id=identity.id, name=identity.name, public_bytes_b64=pubkey.to_bytes().decode()
    )


async def verify_peer_auth(request: Request) -> Peer:
    method = request.headers["X-Forwarded-Method"]
    proto = request.headers["X-Forwarded-proto"]
    host = request.headers["X-Forwarded-host"]
    uri = request.headers["X-Forwarded-uri"]

    prepared_request = requests.Request(
        method=method,
        url=f"{proto}://{host}{uri}",
        headers=request.headers,
        data=await request.body(),
        params=request.query_params,
    ).prepare()
    verify_result = HTTPSignatureAuth.verify(
        prepared_request,
        signature_algorithm=algorithms.RSA_PSS_SHA512,
        key_resolver=await _make_key_resolver(),
    )
    return await get_peer_by_id(verify_result.parameters["keyid"])


async def _make_key_resolver():
    # Pre-load all peers so the synchronous resolve_public_key callback
    # doesn't need to access the async DB connection pool.
    async with db_conn() as conn:
        all_peers = await peers_db.get_all(conn)
    peers_by_prefix = {}
    for p in all_peers:
        peer = Peer(**p)
        # Index by the prefix part (before the colon) for prefix matching
        prefix = peer.id.split(":")[0] if ":" in peer.id else peer.id
        peers_by_prefix[prefix] = peer
        # Also index by full id
        peers_by_prefix[peer.id] = peer

    class _KR(HTTPSignatureKeyResolver):
        def resolve_private_key(self, key_id: str):
            pass

        def resolve_public_key(self, key_id: str):
            # Find peer by prefix match (key_id is typically the prefix part)
            peer = peers_by_prefix.get(key_id)
            if peer is None:
                # Try prefix matching against full ids
                for pid, p in peers_by_prefix.items():
                    if pid.startswith(key_id):
                        peer = p
                        break
            if peer is None:
                raise KeyError(key_id)
            if peer.public_bytes_b64:
                return peer.public_bytes_b64.encode()
            else:
                raise KeyError(f"No public key known for peer id {key_id}")

    return _KR()


@signals.async_on_peer_write.connect
async def _on_peer_write(peer: Peer):
    await update_peer_meta(peer)
