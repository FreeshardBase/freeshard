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
    class _KR(HTTPSignatureKeyResolver):
        def resolve_private_key(self, key_id: str):
            pass

        def resolve_public_key(self, key_id: str):
            # This is called synchronously by the library, so we need a sync path.
            # We use asyncio.get_event_loop().run_until_complete for this edge case.
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context; use a thread to run the coroutine
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    peer = pool.submit(asyncio.run, _get_peer_sync(key_id)).result()
            else:
                peer = loop.run_until_complete(_get_peer_sync(key_id))
            if peer.public_bytes_b64:
                return peer.public_bytes_b64.encode()
            else:
                raise KeyError(f"No public key known for peer id {key_id}")

    return _KR()


async def _get_peer_sync(key_id):
    async with db_conn() as conn:
        p = await peers_db.get_by_id_prefix(conn, key_id)
        if p:
            return Peer(**p)
        else:
            raise KeyError(key_id)


@signals.async_on_peer_write.connect
async def _on_peer_write(peer: Peer):
    await update_peer_meta(peer)
