import logging
from typing import List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from identity_handler import persistence
from identity_handler.service import pubsub

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/peers',
)


class Peer(BaseModel):
	id: str
	name: str
	description: str
	public_bytes_b64: str

	class Config:
		# todo: move this to a superclass
		orm_mode = True
		getter_dict = persistence.util.PeeweeGetterDict


@router.get('', response_model=List[Peer])
def list_all_peers(name: str = None):
	return list(persistence.filter_peers_by_name(name or ''))


@router.get('/{id-prefix}', response_model=Peer)
def get_peer_by_id(id_prefix: str):
	return persistence.find_peer_by_id(id_prefix)


@router.post('', status_code=status.HTTP_204_NO_CONTENT)
def add_peer(p: Peer):
	try:
		new_peer = persistence.add_peer(
			p.id,
			p.name,
			p.description,
			p.public_bytes_b64,
		)
	except persistence.PeerAlreadyExists as e:
		raise HTTPException(status.HTTP_409_CONFLICT) from e
	else:
		pubsub.publish('peer.add', new_peer, as_=Peer)
		log.info(f'added {new_peer}')
