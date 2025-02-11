from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel
from tinydb import Query

from shard_core.database.database import terminals_table
from shard_core.service import human_encoding
from shard_core.util.signals import on_terminal_auth


class Icon(str, Enum):
	UNKNOWN = 'unknown'
	SMARTPHONE = 'smartphone'
	TABLET = 'tablet'
	NOTEBOOK = 'notebook'
	DESKTOP = 'desktop'


class Terminal(BaseModel):
	id: str
	name: str
	icon: Icon = Icon.UNKNOWN
	last_connection: Optional[datetime]

	def __str__(self):
		return f'Terminal[{self.id}, {self.name}]'

	@classmethod
	def create(cls, name: str) -> 'Terminal':
		return Terminal(
			id=human_encoding.random_string(6),
			name=name,
			last_connection=datetime.utcnow()
		)


class InputTerminal(BaseModel):
	name: str
	icon: Icon = Icon.UNKNOWN


@on_terminal_auth.connect
def update_terminal_last_connection(terminal: Terminal):
	with terminals_table() as terminals:  # type: Table
		existing_terminal = Terminal(**(terminals.get(Query().id == terminal.id)))
		existing_terminal.last_connection = datetime.utcnow()
		terminals.update(existing_terminal.dict(), Query().id == existing_terminal.id)
