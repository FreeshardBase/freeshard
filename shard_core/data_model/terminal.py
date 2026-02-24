import asyncio
from datetime import datetime
from enum import Enum
from typing import Optional

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
def update_terminal_last_connection(terminal: Terminal):
    asyncio.create_task(_update_terminal_last_connection_async(terminal))


async def _update_terminal_last_connection_async(terminal: Terminal):
    from shard_core.database.connection import db_conn
    from shard_core.database import terminals as terminals_db

    async with db_conn() as conn:
        existing = await terminals_db.get_by_id(conn, terminal.id)
        if existing:
            await terminals_db.update(
                conn, terminal.id, {"last_connection": datetime.utcnow()}
            )
