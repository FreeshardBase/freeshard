import requests
from common_py.crypto import PublicKey
from fastapi.requests import Request
from http_message_signatures import HTTPSignatureKeyResolver, algorithms
from requests_http_signature import HTTPSignatureAuth
from tinydb import Query
from tinydb.table import Table

from portal_core.database.database import peers_table
from portal_core.model.identity import OutputIdentity
from portal_core.model.peer import Peer
from portal_core.util import signals


def get_peer_by_id(id: str):
	with peers_table() as peers:
		if p := peers.get(Query().id.matches(f'{id}:*')):
			return Peer(**p)
		else:
			raise KeyError(id)


async def update_all_peer_pubkeys():
	with peers_table() as peers:  # type: Table
		peers_without_pubkey = peers.search(Query().public_bytes_b64.exists())
	for peer in peers_without_pubkey:
		update_peer_meta(Peer(**peer))


def update_peer_meta(peer: Peer):
	# todo: this should be done async
	url = f'https://{peer.short_id}.p.getportal.org/core/public/meta/whoareyou'
	peer_identity = OutputIdentity(**requests.get(url).json())

	if not peer_identity.id.startswith(peer.id):
		raise KeyError(f'Portal {peer.short_id} responded with wrong identity {peer_identity.id}')

	updated_peer = output_identity_to_peer(peer_identity)
	with peers_table() as peers:  # type: Table
		peers.update(updated_peer.dict(), Query().id == peer.id)


def output_identity_to_peer(identity: OutputIdentity) -> Peer:
	pubkey = PublicKey(identity.public_key_pem)
	return Peer(
		id=identity.id,
		name=identity.name,
		public_bytes_b64=pubkey.to_bytes().decode()
	)


async def verify_peer_auth(request: Request) -> Peer:
	method = request.headers['X-Forwarded-Method']
	proto = request.headers['X-Forwarded-proto']
	host = request.headers['X-Forwarded-host']
	uri = request.headers['X-Forwarded-uri']

	prepared_request = requests.Request(
		method=method,
		url=f'{proto}://{host}{uri}',
		headers=request.headers,
		data=await request.body(),
		params=request.query_params,
	).prepare()
	verify_result = HTTPSignatureAuth.verify(
		prepared_request,
		signature_algorithm=algorithms.RSA_PSS_SHA512,
		key_resolver=_KR()
	)
	return get_peer_by_id(verify_result.parameters['keyid'])


class _KR(HTTPSignatureKeyResolver):
	def resolve_private_key(self, key_id: str):
		pass

	def resolve_public_key(self, key_id: str):
		peer = get_peer_by_id(key_id)
		if peer.public_bytes_b64:
			return peer.public_bytes_b64.encode()
		else:
			raise KeyError(f'No public key known for peer id {key_id}')


@signals.on_peer_write.connect
def _on_peer_write(peer: Peer):
	update_peer_meta(peer)
