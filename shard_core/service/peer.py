import asyncio
import logging

import httpx
import requests
from fastapi.requests import Request
from http_message_signatures import HTTPSignatureKeyResolver, algorithms
from requests_http_signature import HTTPSignatureAuth

from shard_core.database import db_methods
from shard_core.data_model.identity import OutputIdentity
from shard_core.data_model.peer import Peer
from shard_core.service.crypto import PublicKey
from shard_core.util import signals

log = logging.getLogger(__name__)


def get_peer_by_id(id: str):
    peer_data = db_methods.get_peer_by_id(id)
    if peer_data:
        return Peer(**peer_data)
    else:
        raise KeyError(id)


async def update_all_peer_pubkeys():
    peers_without_pubkey = db_methods.search_peers_without_pubkey()
    await asyncio.gather(
        *[update_peer_meta(Peer(**peer)) for peer in peers_without_pubkey]
    )


async def update_peer_meta(peer: Peer):
    url = f"https://{peer.short_id}.freeshard.cloud/core/public/meta/whoareyou"

    def do_request():
        return requests.get(url=url)

    try:
        response = await asyncio.get_running_loop().run_in_executor(None, do_request)
    except requests.ConnectionError as e:
        log.debug(f"Could not find peer {peer.short_id}: {e}")
        db_methods.update_peer(peer.id, {"is_reachable": False})
        return

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        log.debug(f"Could not update peer meta for {peer.short_id}: {e}")
        db_methods.update_peer(peer.id, {"is_reachable": False})
        return

    peer_identity = OutputIdentity(**response.json())

    if not peer_identity.id.startswith(peer.id):
        raise KeyError(
            f"Portal {peer.short_id} responded with wrong identity {peer_identity.id}"
        )

    updated_peer = output_identity_to_peer(peer_identity)
    db_methods.update_peer(peer.id, updated_peer.dict())


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
        key_resolver=_KR(),
    )
    return get_peer_by_id(verify_result.parameters["keyid"])


class _KR(HTTPSignatureKeyResolver):
    def resolve_private_key(self, key_id: str):
        pass

    def resolve_public_key(self, key_id: str):
        peer = get_peer_by_id(key_id)
        if peer.public_bytes_b64:
            return peer.public_bytes_b64.encode()
        else:
            raise KeyError(f"No public key known for peer id {key_id}")


@signals.async_on_peer_write.connect
async def _on_peer_write(peer: Peer):
    await update_peer_meta(peer)
