import logging
from typing import List

from fastapi import APIRouter, status, HTTPException
from fastapi.responses import Response

from shard_core.db import terminals
from shard_core.db.db_connection import db_conn
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
        return await terminals.get_all(conn)


@router.get("/id/{id_}")
async def get_terminal_by_id(id_: str):
    async with db_conn() as conn:
        terminal = await terminals.get_by_id(conn, id_)
        if terminal:
            return terminal
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/name/{name}", response_model=Terminal)
async def get_terminal_by_name(name: str):
    async with db_conn() as conn:
        all_terminals = await terminals.get_all(conn)
    for t in all_terminals:
        if t.name == name:
            return t
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.put("/id/{id_}")
async def edit_terminal(id_: str, terminal: InputTerminal):
    async with db_conn() as conn:
        terminal_data = await terminals.get_by_id(conn, id_)
        if terminal_data:
            await terminals.update(conn, id_, name=terminal.name, icon=terminal.icon.value, last_connection=terminal_data.last_connection)
            on_terminals_update.send()
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.delete(
    "/id/{id_}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def delete_terminal_by_id(id_: str):
    async with db_conn() as conn:
        await terminals.delete(conn, id_)
    on_terminals_update.send()


@router.get(
    "/pairing-code", response_model=PairingCode, status_code=status.HTTP_201_CREATED
)
async def new_pairing_code(deadline: int = None):
    pairing_code = await pairing.make_pairing_code(deadline=deadline)
    log.info("created new terminal pairing code")
    return pairing_code
