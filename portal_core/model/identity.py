from typing import Optional

import gconf
from common_py import crypto
from email_validator import validate_email, EmailNotValidError
from pydantic import BaseModel, field_validator, computed_field


class Identity(BaseModel):
	id: str
	name: str
	email: Optional[str]
	description: Optional[str]
	private_key: str
	is_default: bool = False

	def __str__(self):
		return f'Identity[{self.short_id}, {self.name}]'

	@field_validator('email')
	def validate_email(cls, v):
		if v:
			try:
				validate_email(v)
			except EmailNotValidError as e:
				raise ValueError(f'invalid email: {e}') from e
		return v

	@classmethod
	def create(cls, name: str, description: str = None, email: str = None) -> 'Identity':
		private_key = crypto.PrivateKey()
		return Identity(
			id=private_key.get_public_key().to_hash_id(),
			name=name,
			description=description,
			email=email,
			private_key=private_key.to_bytes().decode()
		)

	@computed_field
	@property
	def short_id(self) -> str:
		return self.id[0:6]

	@property
	def public_key(self) -> crypto.PublicKey:
		return crypto.PrivateKey(self.private_key).get_public_key()

	@computed_field
	@property
	def public_key_pem(self) -> str:
		return self.public_key.to_bytes().decode()

	@computed_field
	@property
	def domain(self) -> str:
		zone = gconf.get('dns.zone')
		prefix_length = gconf.get('dns.prefix length')
		subdomain = self.id[:prefix_length].lower()
		domain = f'{subdomain}.{zone}'
		return domain


class SafeIdentity(BaseModel):
	domain: str
	id: str
	public_key_pem: str

	@computed_field
	@property
	def short_id(self) -> str:
		return self.id[:6]

	@classmethod
	def from_identity(cls, identity: Identity):
		return cls(
			domain=identity.domain,
			id=identity.id,
			public_key_pem=identity.public_key_pem
		)


class OutputIdentity(BaseModel):
	id: str
	name: str
	email: Optional[str]
	description: Optional[str]
	is_default: bool
	public_key_pem: str
	domain: str


class InputIdentity(BaseModel):
	id: Optional[str] = None
	name: Optional[str] = ''
	email: Optional[str] = ''
	description: Optional[str] = ''

	@field_validator('email')
	def validate_email(cls, v):
		if v:
			try:
				validate_email(v)
			except EmailNotValidError as e:
				raise ValueError(f'invalid email: {e}') from e
		return v
