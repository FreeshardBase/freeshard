from typing import Optional

import gconf
from common_py import crypto
from pydantic import BaseModel


class Identity(BaseModel):
	id: str
	name: str
	description: Optional[str]
	private_key: str
	is_default: bool = False

	def __str__(self):
		return f'Identity[{self.short_id}, {self.name}]'

	@classmethod
	def create(cls, name: str, description: str = None) -> 'Identity':
		private_key = crypto.PrivateKey()
		return Identity(
			id=private_key.get_public_key().to_hash_id(),
			name=name,
			description=description,
			private_key=private_key.to_bytes().decode()
		)

	@property
	def short_id(self):
		return self.id[0:6]

	@property
	def public_key(self) -> crypto.PublicKey:
		return crypto.PrivateKey(self.private_key).get_public_key()

	@property
	def public_key_pem(self) -> str:
		return self.public_key.to_bytes().decode()

	@property
	def domain(self) -> str:
		zone = gconf.get('dns.zone')
		prefix_length = gconf.get('dns.prefix length')
		subdomain = self.id[:prefix_length].lower()
		domain = f'{subdomain}.{zone}'
		return domain

