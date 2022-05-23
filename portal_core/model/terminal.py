from common_py import human_encoding
from pydantic import BaseModel


class Terminal(BaseModel):
	id: str
	name: str

	def __str__(self):
		return f'Terminal[{self.id}, {self.name}]'

	@classmethod
	def create(cls, name: str) -> 'Terminal':
		return Terminal(
			id=human_encoding.random_string(6),
			name=name,
		)


class InputTerminal(BaseModel):
	name: str
