import logging
from typing import List

from fastapi import APIRouter, status, HTTPException
from fastapi.responses import Response

from shard_core.database.connection import db_conn
from shard_core.database import terminals as terminals_db
from shard_core.data_model.terminal import Terminal, InputTerminal
from shard_core.service import pairing
from shard_core.service.pairing import PairingCode
from shard_core.util.signals import on_terminals_update

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/terminals",
)


@router.get("", response_model=List[Terminal])
async def list_all_terminals():
    async with db_conn() as conn:
        return await terminals_db.get_all(conn)


@router.get("/id/{id_}")
async def get_terminal_by_id(id_: str):
    async with db_conn() as conn:
        t = await terminals_db.get_by_id(conn, id_)
    if t:
        return t
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/name/{name}", response_model=Terminal)
async def get_terminal_by_name(name: str):
    async with db_conn() as conn:
        t = await terminals_db.get_by_name(conn, name)
    if t:
        return t
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.put("/id/{id_}")
async def edit_terminal(id_: str, terminal: InputTerminal):
    async with db_conn() as conn:
        t = await terminals_db.get_by_id(conn, id_)
        if t:
            existing_terminal = Terminal(**t)
            existing_terminal.name = terminal.name
            existing_terminal.icon = terminal.icon
            await terminals_db.update(conn, id_, existing_terminal.dict())
            on_terminals_update.send()
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.delete(
    "/id/{id_}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def delete_terminal_by_id(id_: str):
    async with db_conn() as conn:
        await terminals_db.remove(conn, id_)
    on_terminals_update.send()


@router.get(
    "/pairing-code", response_model=PairingCode, status_code=status.HTTP_201_CREATED
)
async def new_pairing_code(deadline: int = None):
    pairing_code = await pairing.make_pairing_code(deadline=deadline)
    log.info("created new terminal pairing code")
    return pairing_code
