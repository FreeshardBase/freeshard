import logging
from typing import List

from fastapi import APIRouter, HTTPException, status
from tinydb import Query

import portal_core.service.peer as peer_service
from portal_core.database.database import peers_table
from portal_core.model.peer import Peer, InputPeer
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
	try:
		return peer_service.get_peer_by_id(id)
	except KeyError as e:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e)


@router.put('', response_model=Peer)
async def put_peer(p: InputPeer):
	with peers_table() as peers:  # type: Table
		if peers.get(Query().id.matches(f'{p.id}:*')):
			peers.update(p.dict(exclude={'id'}), Query().id.matches(f'{p.id}:*'))
			log.debug(f'updated {p}')
		else:
			peers.insert(p.dict())
			log.info(f'added {p}')
	await signals.on_peer_write.send_async(Peer(**p.dict()))
	return p


@router.delete('/{id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_peer(id):
	with peers_table() as peers:  # type: Table
		deleted = peers.remove(Query().id.matches(f'{id}:*'))
		if len(deleted) > 1:
			log.critical(f'during deleting of peer {id}, {len(deleted)} peers were deleted')
		log.info(f'removed peer {deleted[0]}')
