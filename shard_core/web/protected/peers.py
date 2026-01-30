import logging
from typing import List

from fastapi import APIRouter, HTTPException, status

import shard_core.service.peer as peer_service
from shard_core.db import peers
from shard_core.data_model.peer import Peer, InputPeer
from shard_core.util import signals

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/peers",
)


@router.get("", response_model=List[Peer])
def list_all_peers(name: str = None):
    all_peers = peers.get_all()
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
    existing_peer = peers.get_by_id(p.id)
    if existing_peer:
        peer_dict = p.dict(exclude={'id'})
        peers.update(
            existing_peer['id'],
            name=peer_dict.get('name'),
            public_bytes_b64=peer_dict.get('public_bytes_b64'),
            is_reachable=peer_dict.get('is_reachable', True)
        )
        log.debug(f"updated {p}")
    else:
        peers.insert(p.dict())
        log.info(f"added {p}")
    await signals.async_on_peer_write.send_async(Peer(**p.dict()))
    return p


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_peer(id):
    # Get peer with prefix match
    peer_data = peers.get_by_id(id)
    if peer_data:
        peers.delete(peer_data['id'])
        log.info(f"removed peer {peer_data}")
    else:
        log.warning(f"attempted to delete peer {id} but it was not found")
