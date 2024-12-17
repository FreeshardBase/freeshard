import asyncio
import logging

import httpx
import requests
from common_py.crypto import PublicKey
from fastapi.requests import Request
from http_message_signatures import HTTPSignatureKeyResolver, algorithms
from requests_http_signature import HTTPSignatureAuth
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import make_transient
from sqlmodel import select, col

from portal_core.database.database import session
from portal_core.database.models import Peer
from portal_core.model.identity import OutputIdentity

log = logging.getLogger(__name__)


def get_peer_by_id(id: str):
	with session() as session_:
		try:
			peer = session_.exec(select(Peer).where(col(Peer.id).ilike(f'{id}%'))).one()
			session_.refresh(peer, attribute_names=Peer.__table__.columns.keys())
			make_transient(peer)
			return peer
		except NoResultFound:
			raise KeyError(id)

async def update_all_peer_pubkeys():
	with session() as session_:
		peers_without_pubkey = session_.exec(select(Peer).filter(Peer.public_bytes_b64 == None)).all()  # noqa E711
		updated_peers = await asyncio.gather(*[update_peer_meta(Peer(**peer)) for peer in peers_without_pubkey])
		session_.add_all(updated_peers)
		session_.commit()


async def update_peer_meta(peer: Peer) -> Peer:
	url = f'https://{peer.short_id}.p.getportal.org/core/public/meta/whoareyou'

	def do_request():
		return requests.get(url=url)

	try:
		response = await asyncio.get_running_loop().run_in_executor(None, do_request)
	except requests.ConnectionError as e:
		log.debug(f'Could not find peer {peer.short_id}: {e}')
		peer.is_reachable = False
		return peer

	try:
		response.raise_for_status()
	except httpx.HTTPStatusError as e:
		log.debug(f'Could not update peer meta for {peer.short_id}: {e}')
		peer.is_reachable = False
		return peer

	peer_identity = OutputIdentity(**response.json())

	if not peer_identity.id.startswith(peer.id):
		raise KeyError(f'Portal {peer.short_id} responded with wrong identity {peer_identity.id}')

	updated_peer = output_identity_to_peer(peer_identity)
	return updated_peer


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
