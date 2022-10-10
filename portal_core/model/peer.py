from typing import Optional

from common_py.crypto import PublicKey
from pydantic import BaseModel, validator, root_validator


class Peer(BaseModel):
	id: str
	name: Optional[str]
	public_bytes_b64: Optional[str]

	@validator('id')
	def must_be_long_enough(cls, v):
		if len(v) < 6:
			raise ValueError(f'{v} is too short, must be at least 6 characters')
		return v

	@root_validator
	def public_bytes_must_match_id(cls, values):
		if values['public_bytes_b64']:
			pubkey = PublicKey(values['public_bytes_b64'])
			if not pubkey.to_hash_id().startswith(values['id']):
				raise ValueError('public key and id do not match')
		return values

	def __str__(self):
		return f'Peer[{self.short_id}]'

	@property
	def short_id(self):
		return self.id[0:6]


class InputPeer(BaseModel):
	id: str
	name: Optional[str]

	@validator('id')
	def must_be_long_enough(cls, v):
		if len(v) < 6:
			raise ValueError(f'{v} is too short, must be at least 6 characters')
		return v
