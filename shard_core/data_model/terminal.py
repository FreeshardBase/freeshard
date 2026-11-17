from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel

from shard_core.service import human_encoding
from shard_core.util.signals import on_terminal_auth


class Icon(str, Enum):
    UNKNOWN = "unknown"
    SMARTPHONE = "smartphone"
    TABLET = "tablet"
    NOTEBOOK = "notebook"
    DESKTOP = "desktop"


class Terminal(BaseModel):
    id: str
    name: str
    icon: Icon = Icon.UNKNOWN
    last_connection: Optional[datetime] = None
    paired_at: Optional[datetime] = None
    user_id: Optional[int] = None

    def __str__(self):
        return f"Terminal[{self.id}, {self.name}]"

    @classmethod
    def create(cls, name: str, user_id: Optional[int] = None) -> "Terminal":
        now = datetime.now(timezone.utc)
        return Terminal(
            id=human_encoding.random_string(6),
            name=name,
            last_connection=now,
            paired_at=now,
            user_id=user_id,
        )


class InputTerminal(BaseModel):
    name: str
    icon: Icon = Icon.UNKNOWN


class LockoutState(str, Enum):
    """Per-app delivery state of one back-channel logout for an unpaired
    device. Derived when read (service/terminal_lockouts._derive_state), never
    stored. Delivered rows are not reported."""

    WAITING_FOR_START = "waiting_for_start"
    RETRYING = "retrying"
    WAITING_FOR_INSTALL = "waiting_for_install"
    FAILED = "failed"


class Lockout(BaseModel):
    app_name: str
    state: LockoutState


class UnpairedTerminal(BaseModel):
    id: str
    name: str
    icon: Icon = Icon.UNKNOWN
    paired_at: Optional[datetime] = None
    last_connection: Optional[datetime] = None
    unpaired_at: Optional[datetime] = None
    lockouts: List[Lockout] = []


@on_terminal_auth.connect
async def update_terminal_last_connection(terminal: Terminal):
    from shard_core.database.connection import db_conn
    from shard_core.database import terminals as db_terminals

    async with db_conn() as conn:
        await db_terminals.update_connected(
            conn, terminal.id, {"last_connection": datetime.now(timezone.utc)}
        )
