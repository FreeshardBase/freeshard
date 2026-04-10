import logging

from fastapi import APIRouter, HTTPException, status, Response

from shard_core.database.connection import db_conn
from shard_core.database import terminals as db_terminals
from shard_core.database import identities as db_identities
from shard_core.data_model.identity import Identity
from shard_core.data_model.terminal import Terminal, InputTerminal
from shard_core.service import pairing
from shard_core.util.signals import (
    async_on_first_terminal_add,
    on_terminals_update,
    on_terminal_add,
)

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/pair",
)


@router.post("/terminal", status_code=status.HTTP_201_CREATED)
async def add_terminal(code: str, terminal: InputTerminal, response: Response):
    try:
        await pairing.redeem_pairing_code(code)
    except (KeyError, pairing.InvalidPairingCode, pairing.PairingCodeExpired) as e:
        log.info(e)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED) from e

    new_terminal = Terminal.create(terminal.name)
    async with db_conn() as conn:
        await db_terminals.insert(conn, new_terminal.model_dump())
        is_first_terminal = await db_terminals.count(conn) == 1

    async with db_conn() as conn:
        default_row = await db_identities.get_default(conn)
    default_identity = Identity(**default_row)

    jwt = await pairing.create_terminal_jwt(new_terminal.id)
    response.set_cookie(
        "authorization",
        jwt,
        domain=default_identity.domain,
        secure=True,
        httponly=True,
        expires=60 * 60 * 24 * 356 * 10,
    )

    await on_terminals_update.send_async()
    on_terminal_add.send(new_terminal)
    if is_first_terminal:
        await async_on_first_terminal_add.send_async(new_terminal)

    log.info(f"added {new_terminal}")
