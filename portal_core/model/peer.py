import base64
from typing import Optional

from pydantic import BaseModel


class Peer(BaseModel):
	id: str
	name: str
	public_bytes_b64: Optional[str]

	def __str__(self):
		return f'Peer[{self.short_id}, {self.name}]'

	@property
	def short_id(self):
		return self.id[0:6]
