import logging
from typing import List

from fastapi import APIRouter, HTTPException, status

from shard_core.database.connection import db_conn
from shard_core.database import peers as db_peers
from shard_core.data_model.peer import Peer, InputPeer
from shard_core.util import signals
import shard_core.service.peer as peer_service

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/peers",
)


@router.get("", response_model=List[Peer])
async def list_all_peers(name: str = None):
    async with db_conn() as conn:
        if name:
            return await db_peers.search_by_name(conn, name)
        else:
            return await db_peers.get_all(conn)


@router.get("/{id}", response_model=Peer)
async def get_peer_by_id(id):
    try:
        return await peer_service.get_peer_by_id(id)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.put("", response_model=Peer)
async def put_peer(p: InputPeer):
    async with db_conn() as conn:
        existing = await db_peers.get_by_id_prefix(conn, p.id)
        if existing:
            await db_peers.update_by_id_prefix(conn, p.id, p.model_dump(exclude={"id"}))
            log.debug(f"updated {p}")
        else:
            peer_data = {
                "public_bytes_b64": None,
                "is_reachable": True,
                **p.model_dump(),
            }
            await db_peers.insert(conn, peer_data)
            log.info(f"added {p}")
    peer = Peer(id=p.id, name=p.name)
    await signals.async_on_peer_write.send_async(peer)
    return peer


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_peer(id):
    async with db_conn() as conn:
        deleted = await db_peers.remove_by_id_prefix(conn, id)
    if deleted > 1:
        log.critical(f"during deleting of peer {id}, {deleted} peers were deleted")
    log.info(f"removed peer {id}")
