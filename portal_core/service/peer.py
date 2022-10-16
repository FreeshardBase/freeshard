import asyncio
import atexit

import httpx
from common_py.crypto import PublicKey
from fastapi.requests import Request
from http_message_signatures import HTTPSignatureKeyResolver, algorithms, VerifyResult
from requests_http_signature import HTTPSignatureAuth
from tinydb import Query
from tinydb.table import Table

from portal_core.database.database import peers_table
from portal_core.model.peer import Peer
from portal_core.util import signals

httpx_client = httpx.AsyncClient()
atexit.register(asyncio.run, httpx_client.aclose())


def get_peer_by_id(id: str):
	with peers_table() as peers:
		if p := peers.get(Query().id.matches(f'{id}:*')):
			return Peer(**p)
		else:
			raise KeyError(id)


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


def verify_peer_auth(request: Request) -> Peer:
	verify_result = HTTPSignatureAuth.verify(
		request,
		signature_algorithm=algorithms.RSA_PSS_SHA512,
		key_resolver=_KR()
	)
	return get_peer_by_id(verify_result.parameters['keyid'])


class _KR(HTTPSignatureKeyResolver):
	def resolve_private_key(self, key_id: str):
		pass

	def resolve_public_key(self, key_id: str):
		peer = get_peer_by_id(key_id)
		return peer.public_bytes_b64.encode()


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
