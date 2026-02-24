import logging
from typing import List

from fastapi import APIRouter, HTTPException, status

import shard_core.service.peer as peer_service
from shard_core.database.connection import db_conn
from shard_core.database import peers as peers_db
from shard_core.data_model.peer import Peer, InputPeer
from shard_core.util import signals

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/peers",
)


@router.get("", response_model=List[Peer])
async def list_all_peers(name: str = None):
    async with db_conn() as conn:
        if name:
            return await peers_db.search_by_name(conn, name)
        else:
            return await peers_db.get_all(conn)


@router.get("/{id}", response_model=Peer)
async def get_peer_by_id(id):
    try:
        return await peer_service.get_peer_by_id(id)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e)


@router.put("", response_model=Peer)
async def put_peer(p: InputPeer):
    async with db_conn() as conn:
        await peers_db.upsert(conn, p.dict())
    await signals.async_on_peer_write.send_async(Peer(**p.dict()))
    return p


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_peer(id):
    async with db_conn() as conn:
        deleted = await peers_db.remove_by_id_prefix(conn, id)
    if deleted > 1:
        log.critical(
            f"during deleting of peer {id}, {deleted} peers were deleted"
        )
    log.info(f"removed peer {id}")
