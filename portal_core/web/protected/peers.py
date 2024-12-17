import logging
from typing import List

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import NoResultFound
from sqlmodel import select, col

import portal_core.service.peer as peer_service
from portal_core.database.database import session
from portal_core.database.models import Peer
from portal_core.model.peer import InputPeer
from portal_core.service.peer import update_peer_meta

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/peers',
)


@router.get('', response_model=List[Peer])
def list_all_peers(name: str = None):
	with session() as session_:
		statement = select(Peer)
		if name:
			statement = statement.where(col(Peer.name).ilike(f'%{name}%'))
		return session_.exec(statement).all()


@router.get('/{id}', response_model=Peer)
def get_peer_by_id(id):
	try:
		return peer_service.get_peer_by_id(id)
	except KeyError as e:
		raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e)


@router.put('', response_model=Peer)
async def put_peer(p: InputPeer):
	with session() as session_:
		statement = select(Peer).where(col(Peer.id).ilike(f'{id}%'))
		try:
			peer = session_.exec(statement).one()
			for k, v in p.model_dump(exclude_unset=True).items():
				setattr(peer, k, v)
			log.debug(f'updated {p}')
		except NoResultFound:
			peer = Peer.from_input_peer(p)
			log.info(f'added {p}')

		peer = await update_peer_meta(peer)

		session_.add(peer)
		session_.commit()
		session_.refresh(peer)

	return peer


@router.delete('/{id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_peer(id):
	with session() as session_:
		statement = select(Peer).where(col(Peer.id).ilike(f'{id}%'))
		try:
			peer = session_.exec(statement).one()
		except NoResultFound:
			log.warning(f'peer {id} cannot be deleted: not found')
			return
		session_.delete(peer)
		session_.commit()
		log.info(f'removed {peer}')
