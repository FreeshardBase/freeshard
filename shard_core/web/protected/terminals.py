import logging
from typing import List

from fastapi import APIRouter, status, HTTPException
from fastapi.responses import Response

from shard_core.db import terminals
from shard_core.data_model.terminal import Terminal, InputTerminal
from shard_core.service import pairing
from shard_core.service.pairing import PairingCode
from shard_core.util.signals import on_terminals_update

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/terminals",
)


@router.get("", response_model=List[Terminal])
def list_all_terminals():
    return terminals.get_all()


@router.get("/id/{id_}")
def get_terminal_by_id(id_: str):
    terminal_data = terminals.get_by_id(id_)
    if terminal_data:
        return terminal_data
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/name/{name}", response_model=Terminal)
def get_terminal_by_name(name: str):
    all_terminals = terminals.get_all()
    for t in all_terminals:
        if t.get('name') == name:
            return t
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.put("/id/{id_}")
def edit_terminal(id_: str, terminal: InputTerminal):
    terminal_data = terminals.get_by_id(id_)
    if terminal_data:
        terminals.update(id_, name=terminal.name, icon=terminal.icon, last_connection=terminal_data.get('last_connection'))
        on_terminals_update.send()
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.delete(
    "/id/{id_}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def delete_terminal_by_id(id_: str):
    terminals.delete(id_)
    on_terminals_update.send()


@router.get(
    "/pairing-code", response_model=PairingCode, status_code=status.HTTP_201_CREATED
)
def new_pairing_code(deadline: int = None):
    pairing_code = pairing.make_pairing_code(deadline=deadline)
    log.info("created new terminal pairing code")
    return pairing_code
