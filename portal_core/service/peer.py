import asyncio
import atexit

import httpx
from common_py.crypto import PublicKey
from tinydb import Query
from tinydb.table import Table

from portal_core.database.database import peers_table
from portal_core.model.peer import Peer
from portal_core.util import signals

httpx_client = httpx.AsyncClient()
atexit.register(asyncio.run, httpx_client.aclose())


async def update_all_peer_pubkeys():
	with peers_table() as peers:  # type: Table
		peers_without_pubkey = peers.search(Query().public_bytes_b64.exists())
	futures = (_update_peer_with_pubkey(Peer(**p)) for p in peers_without_pubkey)
	await asyncio.gather(futures)


async def update_peer_pubkey(portal_id: str):
	with peers_table() as peers:  # type: Table
		if peer := Peer(**peers.get(Query().id.matches(f'{portal_id}:*'))):
			peer = await _update_peer_with_pubkey(peer)
			peers.update(peer.dict(), Query().id.matches(f'{portal_id}:*'))


async def _update_peer_with_pubkey(peer: Peer) -> Peer:
	pubkey = await _query_peer_for_public_key(peer.short_id)
	peer.public_bytes_b64 = pubkey.to_bytes().decode()
	return peer


async def _query_peer_for_public_key(portal_id: str) -> PublicKey:
	url = f'https://{portal_id}.p.getportal.org/core/public/meta/whoareyou'

	response = await httpx_client.get(url)
	whoareyou = response.json()

	pubkey = PublicKey(whoareyou['public_key_pem'])
	if not pubkey.to_hash_id().startswith(portal_id):
		raise KeyError(f'Portal id {portal_id} does not match its public key')
	return pubkey


@signals.on_peer_write.connect
def _on_peer_write(peer: Peer):
	asyncio.run(update_peer_pubkey(peer.id))
