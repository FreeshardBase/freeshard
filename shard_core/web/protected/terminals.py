import logging
from typing import List

from fastapi import APIRouter, status, HTTPException
from fastapi.responses import Response

from shard_core.database.connection import db_conn
from shard_core.database import oidc as db_oidc
from shard_core.database import terminals as db_terminals
from shard_core.data_model.terminal import Terminal, InputTerminal
from shard_core.service import oidc_backchannel_logout, pairing
from shard_core.service.pairing import PairingCode
from shard_core.util.signals import on_terminals_update, on_backchannel_outbox_update

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/terminals",
)


@router.get("", response_model=List[Terminal])
async def list_all_terminals():
    async with db_conn() as conn:
        return await db_terminals.get_all(conn)


@router.get("/id/{id_}")
async def get_terminal_by_id(id_: str):
    async with db_conn() as conn:
        t = await db_terminals.get_by_id(conn, id_)
    if t:
        return t
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/name/{name}", response_model=Terminal)
async def get_terminal_by_name(name: str):
    async with db_conn() as conn:
        t = await db_terminals.get_by_name(conn, name)
    if t:
        return t
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.put("/id/{id_}")
async def edit_terminal(id_: str, terminal: InputTerminal):
    async with db_conn() as conn:
        t = await db_terminals.get_by_id(conn, id_)
        if t:
            await db_terminals.update(
                conn, id_, {"name": terminal.name, "icon": terminal.icon}
            )
            await on_terminals_update.send_async()
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.delete(
    "/id/{id_}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def delete_terminal_by_id(id_: str):
    async with db_conn() as conn:
        # Must run first: it reads the terminal's still-live OIDC grants,
        # and both revoke_for_terminal (marks them revoked) and
        # terminals.remove (ON DELETE SET NULL severs the FK) destroy the
        # only way to find them afterwards.
        await oidc_backchannel_logout.enqueue_for_terminal(conn, id_)
        await db_oidc.revoke_for_terminal(conn, id_)
        await db_terminals.remove(conn, id_)
    await on_terminals_update.send_async()
    # Fired after the transaction commits so the barrier's rebuild query sees
    # the freshly enqueued rows and holds this app's traffic on the very next
    # request.
    await on_backchannel_outbox_update.send_async()


@router.get(
    "/pairing-code", response_model=PairingCode, status_code=status.HTTP_201_CREATED
)
async def new_pairing_code(deadline: int = None):
    pairing_code = await pairing.make_pairing_code(deadline=deadline)
    log.info("created new terminal pairing code")
    return pairing_code
