from typing import Optional

from email_validator import validate_email, EmailNotValidError
from pydantic import BaseModel, field_validator, computed_field

from portal_core.database.models import Identity


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
	id: str | None = None
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
