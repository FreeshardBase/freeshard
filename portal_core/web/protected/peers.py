import logging
from typing import List

from common_py.crypto import PublicKey
from fastapi import APIRouter, HTTPException, status
from tinydb import Query

from portal_core.database.database import peers_table
from portal_core.model.peer import Peer
from portal_core.util import signals

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/peers',
)


@router.get('', response_model=List[Peer])
def list_all_peers(name: str = None):
	with peers_table() as peers:  # type: Table
		if name:
			return peers.search(Query().name.search(name))
		else:
			return peers.all()


@router.get('/{id}', response_model=Peer)
def get_peer_by_id(id):
	with peers_table() as peers:
		if p := peers.get(Query().id == id):
			return p
		else:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.put('', response_model=Peer, status_code=status.HTTP_201_CREATED)
def put_peer(p: Peer):
	if p.public_bytes_b64:
		if not PublicKey(p.public_bytes_b64).to_hash_id().startswith(p.id):
			raise HTTPException(
				status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
				detail='public key and id do not match')

	with peers_table() as peers:  # type: Table
		peers.upsert(p.dict(), Query().id == p.id)

	signals.on_peer_write.send(p)
	log.info(f'put {p}')
	return p
