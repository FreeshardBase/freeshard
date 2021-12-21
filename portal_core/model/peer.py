import base64

from pydantic import BaseModel


class Peer(BaseModel):
	id: str
	name: str
	public_bytes: bytes

	def __str__(self):
		return f'Peer[{self.short_id}, {self.name}]'

	@property
	def short_id(self):
		return self.id[0:6]

	@property
	def public_bytes_b64(self) -> str:
		return str(base64.b64encode(self.public_bytes))
