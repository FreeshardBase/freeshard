from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel

from shard_core.db import terminals
from shard_core.db.db_connection import db_conn
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
    last_connection: Optional[datetime]

    def __str__(self):
        return f"Terminal[{self.id}, {self.name}]"

    @classmethod
    def create(cls, name: str) -> "Terminal":
        return Terminal(
            id=human_encoding.random_string(6),
            name=name,
            last_connection=datetime.utcnow(),
        )


class InputTerminal(BaseModel):
    name: str
    icon: Icon = Icon.UNKNOWN


@on_terminal_auth.connect
async def update_terminal_last_connection(terminal: Terminal):
    async with db_conn() as conn:
        existing_terminal = await terminals.get_by_id(conn, terminal.id)
        if existing_terminal:
            existing_terminal.last_connection = datetime.utcnow()
            await terminals.update(conn, existing_terminal.id, name=existing_terminal.name, icon=existing_terminal.icon.value, last_connection=existing_terminal.last_connection)
