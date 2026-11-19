import logging
from typing import List

from fastapi import APIRouter, status, HTTPException
from fastapi.responses import Response

from shard_core.database.connection import db_conn
from shard_core.database import oidc as db_oidc
from shard_core.database import terminals as db_terminals
from shard_core.data_model.terminal import Terminal, InputTerminal, UnpairedTerminal
from shard_core.service import oidc_backchannel_logout, pairing, terminal_lockouts
from shard_core.service.pairing import PairingCode
from shard_core.util.signals import on_terminals_update, on_backchannel_outbox_update

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/terminals",
)


@router.get("", response_model=List[Terminal])
async def list_all_terminals():
    async with db_conn() as conn:
        return await db_terminals.list_paired(conn)


@router.get("/unpaired", response_model=List[UnpairedTerminal])
async def list_unpaired_terminals():
    return await terminal_lockouts.list_unpaired_terminals()


@router.get("/id/{id_}", response_model=Terminal)
async def get_terminal_by_id(id_: str):
    async with db_conn() as conn:
        t = await db_terminals.get_paired_by_id(conn, id_)
    if t:
        return t
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/name/{name}", response_model=Terminal)
async def get_terminal_by_name(name: str):
    async with db_conn() as conn:
        t = await db_terminals.get_paired_by_name(conn, name)
    if t:
        return t
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.put("/id/{id_}")
async def edit_terminal(id_: str, terminal: InputTerminal):
    async with db_conn() as conn:
        t = await db_terminals.get_paired_by_id(conn, id_)
        if t:
            await db_terminals.update_paired(
                conn, id_, {"name": terminal.name, "icon": terminal.icon}
            )
            await on_terminals_update.send_async()
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.delete(
    "/id/{id_}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def unpair_terminal_by_id(id_: str):
    """Unpair a device: enqueue its lockouts, revoke its OIDC grants,
    and flag it unpaired. A device that owed no lockout is deleted outright;
    otherwise the flagged row stays until every lockout is delivered."""
    async with db_conn() as conn:
        if not await db_terminals.get_paired_by_id(conn, id_):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        # Must run first: it reads the device's still-live OIDC grants, which
        # revoke_for_terminal then marks revoked.
        enqueued = await oidc_backchannel_logout.enqueue_for_terminal(conn, id_)
        await db_oidc.revoke_for_terminal(conn, id_)
        if enqueued:
            await db_terminals.mark_unpaired(conn, id_)
        else:
            await db_terminals.remove(conn, id_)
    await on_terminals_update.send_async()
    # After commit, so the rebuild query sees the enqueued rows.
    await on_backchannel_outbox_update.send_async()


@router.post(
    "/unpaired/{id_}/retry",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def retry_unpaired_terminal(id_: str):
    async with db_conn() as conn:
        if not await db_terminals.get_unpaired_by_id(conn, id_):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        await db_oidc.reset_failed_outbox_for_terminal(conn, id_)
    # Rebuild the barrier (the app owes a logout again) and push the new state
    # before draining, which attempts delivery and signals again on its own.
    await on_backchannel_outbox_update.send_async()
    await oidc_backchannel_logout.drain_due_outbox()


@router.delete(
    "/unpaired/{id_}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def dismiss_unpaired_terminal(id_: str):
    """Dismiss an unpaired device: delete it and, by cascade, its remaining
    lockouts, which are then never delivered. The barrier set is rebuilt."""
    async with db_conn() as conn:
        if not await db_terminals.get_unpaired_by_id(conn, id_):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        await db_terminals.remove(conn, id_)
    await on_backchannel_outbox_update.send_async()


@router.get(
    "/pairing-code", response_model=PairingCode, status_code=status.HTTP_201_CREATED
)
async def new_pairing_code(deadline: int = None):
    pairing_code = await pairing.make_pairing_code(deadline=deadline)
    log.info("created new terminal pairing code")
    return pairing_code
