import logging
from typing import List

from fastapi import APIRouter, HTTPException, status

import shard_core.service.peer as peer_service
from shard_core.db import peers
from shard_core.db.db_connection import db_conn
from shard_core.data_model.peer import Peer, InputPeer
from shard_core.util import signals

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/peers",
)


@router.get("", response_model=List[Peer])
async def list_all_peers(name: str = None):
    async with db_conn() as conn:
        all_peers = await peers.get_all(conn)
    if name:
        return [p for p in all_peers if name.lower() in p.name.lower()]
    else:
        return all_peers


@router.get("/{id}", response_model=Peer)
async def get_peer_by_id(id):
    try:
        return await peer_service.get_peer_by_id(id)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.put("", response_model=Peer)
async def put_peer(p: InputPeer):
    # Check if peer exists (with prefix match)
    async with db_conn() as conn:
        existing_peer = await peers.get_by_id(conn, p.id)
        if existing_peer:
            peer_dict = p.dict(exclude={'id'})
            await peers.update(
                conn,
                existing_peer.id,
                name=peer_dict.get('name'),
                public_bytes_b64=peer_dict.get('public_bytes_b64'),
                is_reachable=peer_dict.get('is_reachable', True)
            )
            log.debug(f"updated {p}")
        else:
            await peers.insert(conn, Peer(**p.dict()))
            log.info(f"added {p}")
    await signals.async_on_peer_write.send_async(Peer(**p.dict()))
    return p


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_peer(id):
    # Get peer with prefix match
    async with db_conn() as conn:
        peer_data = await peers.get_by_id(conn, id)
        if peer_data:
            await peers.delete(conn, peer_data.id)
            log.info(f"removed peer {peer_data}")
        else:
            log.warning(f"attempted to delete peer {id} but it was not found")
