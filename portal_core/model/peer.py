from typing import Optional

from pydantic import BaseModel, validator


class Peer(BaseModel):
	id: str
	name: Optional[str]
	public_bytes_b64: Optional[str]

	@validator('id')
	def must_be_long_enough(cls, v):
		if len(v) < 6:
			raise ValueError(f'{v} is too short, must be at least 6 characters')
		return v

	def __str__(self):
		return f'Peer[{self.short_id}]'

	@property
	def short_id(self):
		return self.id[0:6]
