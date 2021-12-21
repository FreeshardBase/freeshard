from common_py import crypto
from pydantic import BaseModel


class Identity(BaseModel):
	id: str
	name: str
	description: str
	private_bytes: bytes
	is_default: bool

	def __str__(self):
		return f'Identity[{self.short_id}, {self.name}]'

	@classmethod
	def create(cls, name: str, description: str = None) -> 'Identity':
		private_key = crypto.PrivateKey()
		return Identity(
			id=private_key.get_public_key().to_hash_id(),
			name=name,
			description=description,
			private_bytes=private_key.to_bytes()
		)

	@property
	def short_id(self):
		return self.id[0:6]

	@property
	def public_key(self) -> crypto.PublicKey:
		return crypto.PrivateKey(self.private_bytes).get_public_key()

	@property
	def public_key_pem(self) -> str:
		return self.public_key.to_bytes().decode()
