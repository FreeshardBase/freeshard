from enum import Enum

from common_py import human_encoding
from pydantic import BaseModel


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

	def __str__(self):
		return f'Terminal[{self.id}, {self.name}]'

	@classmethod
	def create(cls, name: str) -> 'Terminal':
		return Terminal(
			id=human_encoding.random_string(6),
			name=name,
			icon=Icon.UNKNOWN,
		)


class InputTerminal(BaseModel):
	name: str
	icon: Icon = Icon.UNKNOWN
