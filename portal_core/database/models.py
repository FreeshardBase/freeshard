import typing
from datetime import datetime, timezone
from enum import Enum

import gconf
from common_py import crypto
from common_py import human_encoding
from common_py.crypto import PublicKey
from pydantic import computed_field, field_validator, model_validator
from sqlmodel import SQLModel, Field, Column

from portal_core.database.util import UTCTimestamp
from portal_core.model.peer import InputPeer


class Identity(SQLModel, table=True):
	id: str = Field(primary_key=True)
	name: str
	email: str | None = None
	description: str | None = None
	private_key: str
	is_default: bool = False

	class Config:
		fields = {'public_key': {'exclude': True}}

	def __str__(self):
		return f'Identity[{self.short_id}, {self.name}]'

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


class Icon(str, Enum):
	UNKNOWN = 'unknown'
	SMARTPHONE = 'smartphone'
	TABLET = 'tablet'
	NOTEBOOK = 'notebook'
	DESKTOP = 'desktop'

class Terminal(SQLModel, table=True):
	id: str = Field(primary_key=True)
	name: str
	icon: Icon = Icon.UNKNOWN
	last_connection: datetime | None = Field(default=None, sa_column=Column(UTCTimestamp, nullable=True))

	def __str__(self):
		return f'Terminal[{self.id}, {self.name}]'

	@classmethod
	def create(cls, name: str) -> 'Terminal':
		return Terminal(
			id=human_encoding.random_string(6),
			name=name,
			last_connection=datetime.now(timezone.utc)
		)


class InstallationReason(str, Enum):
	UNKNOWN = 'unknown'
	CONFIG = 'config'
	CUSTOM = 'custom'
	STORE = 'store'


class Status(str, Enum):
	UNKNOWN = 'unknown'
	INSTALLATION_QUEUED = 'installation_queued'
	INSTALLING = 'installing'
	STOPPED = 'stopped'
	RUNNING = 'running'
	UNINSTALLATION_QUEUED = 'uninstallation_queued'
	UNINSTALLING = 'uninstalling'
	REINSTALLATION_QUEUED = 'reinstallation_queued'
	REINSTALLING = 'reinstalling'
	DOWN = 'down'
	ERROR = 'error'


class InstalledApp(SQLModel, table=True):
	name: str = Field(primary_key=True)
	installation_reason: InstallationReason = InstallationReason.UNKNOWN
	status: str = Status.UNKNOWN
	last_access: datetime | None = Field(default=None, sa_column=Column(UTCTimestamp, nullable=True))


class Peer(SQLModel, table=True):
	id: str = Field(primary_key=True)
	name: str | None = None
	public_bytes_b64: str | None = None
	is_reachable: bool = True

	@classmethod
	def from_input_peer(cls, input_peer: InputPeer) -> typing.Self:
		return Peer(
			id=input_peer.id,
			name=input_peer.name,
		)

	@field_validator('id')
	def must_be_long_enough(cls, v):
		if len(v) < 6:
			raise ValueError(f'{v} is too short, must be at least 6 characters')
		return v

	@model_validator(mode='before')
	def public_bytes_must_match_id(cls, values):
		if 'public_bytes_b64' in values:
			pubkey = PublicKey(values['public_bytes_b64'])
			if not pubkey.to_hash_id().startswith(values['id']):
				raise ValueError('public key and id do not match')
		return values

	def __str__(self):
		return f'Peer[{self.short_id}]'

	@property
	def short_id(self):
		return self.id[0:6]

	@property
	def pubkey(self):
		return PublicKey(self.public_bytes_b64)


class TourStatus(str, Enum):
	SEEN = 'seen'
	UNSEEN = 'unseen'


class Tour(SQLModel, table=True):
	name: str = Field(primary_key=True)
	status: TourStatus = TourStatus.UNSEEN
