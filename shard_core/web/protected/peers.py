import logging
from typing import List

from fastapi import APIRouter, HTTPException, status

import shard_core.service.peer as peer_service
from shard_core.database import db_methods
from shard_core.data_model.peer import Peer, InputPeer
from shard_core.util import signals

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/peers",
)


@router.get("", response_model=List[Peer])
def list_all_peers(name: str = None):
    all_peers = db_methods.get_all_peers()
    if name:
        return [p for p in all_peers if name.lower() in p.get('name', '').lower()]
    else:
        return all_peers


@router.get("/{id}", response_model=Peer)
def get_peer_by_id(id):
    try:
        return peer_service.get_peer_by_id(id)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e)


@router.put("", response_model=Peer)
async def put_peer(p: InputPeer):
    # Check if peer exists (with prefix match)
    existing_peer = db_methods.get_peer_by_id(p.id)
    if existing_peer:
        db_methods.update_peer(existing_peer['id'], p.dict(exclude={'id'}))
        log.debug(f"updated {p}")
    else:
        db_methods.insert_peer(p.dict())
        log.info(f"added {p}")
    await signals.async_on_peer_write.send_async(Peer(**p.dict()))
    return p


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_peer(id):
    # Get peer with prefix match
    peer_data = db_methods.get_peer_by_id(id)
    if peer_data:
        db_methods.delete_peer(peer_data['id'])
        log.info(f"removed peer {peer_data}")
    else:
        log.warning(f"attempted to delete peer {id} but it was not found")
