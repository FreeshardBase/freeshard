"""Read model for unpaired devices and their per-app lockout state.

A lockout is one outbox row: one back-channel logout notification for one app
session of an unpaired device. Its state is derived when read from the
delivery status and the app's install status (see LockoutState); it is never
stored. Delivered rows are reaped with their device and so never appear here.

Both GET /protected/terminals/unpaired and the unpaired_terminals_update
websocket message render the list this module builds, so they never diverge.
"""

from shard_core.data_model.app_meta import Status
from shard_core.data_model.terminal import Lockout, LockoutState, UnpairedTerminal
from shard_core.database import oidc as db_oidc
from shard_core.database import terminals as db_terminals
from shard_core.database.connection import db_conn


def _derive_state(delivery_status: str, app_status: str | None) -> LockoutState:
    """app_status is None when the app is not installed."""
    if delivery_status == "failed":
        return LockoutState.FAILED
    if app_status is None:
        return LockoutState.WAITING_FOR_INSTALL
    if app_status == Status.RUNNING.value:
        return LockoutState.RETRYING
    return LockoutState.WAITING_FOR_START


async def list_unpaired_terminals() -> list[UnpairedTerminal]:
    async with db_conn() as conn:
        terminals = await db_terminals.list_unpaired(conn)
        outbox_rows = await db_oidc.get_undelivered_outbox_with_app_status(conn)

    lockouts_by_terminal: dict[str, list[Lockout]] = {}
    for row in outbox_rows:
        lockouts_by_terminal.setdefault(row["terminal_id"], []).append(
            Lockout(
                app_name=row["app_name"],
                state=_derive_state(row["status"], row["app_status"]),
            )
        )

    return [
        UnpairedTerminal(
            id=t["id"],
            name=t["name"],
            icon=t["icon"],
            paired_at=t["paired_at"],
            last_connection=t["last_connection"],
            unpaired_at=t["unpaired_at"],
            lockouts=lockouts_by_terminal.get(t["id"], []),
        )
        for t in terminals
    ]
