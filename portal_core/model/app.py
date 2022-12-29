from enum import Enum
from typing import Optional, List, Dict, Union

from pydantic import BaseModel, root_validator, validator

from portal_core.model import app_migration

CURRENT_VERSION = '4.0'


class InstallationReason(str, Enum):
	UNKNOWN = 'unknown'
	CONFIG = 'config'
	CUSTOM = 'custom'
	STORE = 'store'


class Access(str, Enum):
	PUBLIC = 'public'
	PRIVATE = 'private'
	PEER = 'peer'


class Status(str, Enum):
	UNKNOWN = 'unknown'
	RUNNING = 'running'


class Service(str, Enum):
	POSTGRES = 'postgres'
	DOCKER_SOCK_RO = 'docker_sock_ro'


class SharedDir(str, Enum):
	DOCUMENTS = 'documents'
	MEDIA = 'media'
	MUSIC = 'music'


class EntrypointPort(str, Enum):
	HTTPS_443 = 'http'
	MQTTS_1883 = 'mqtt'


class StoreInfo(BaseModel):
	description_short: Optional[str]
	description_long: Optional[Union[str, List[str]]]
	hint: Optional[Union[str, List[str]]]
	is_featured: Optional[bool]


class Postgres(BaseModel):
	connection_string: str
	userspec: str
	user: str
	password: str
	hostspec: str
	host: str
	port: int


class DataDir(BaseModel):
	path: str
	uid: Optional[int]
	gid: Optional[int]
	shared_dir: Optional[SharedDir]


class Path(BaseModel):
	access: Access
	headers: Optional[Dict[str, str]]


class Entrypoint(BaseModel):
	container_port: int
	entrypoint_port: EntrypointPort


class Lifecycle(BaseModel):
	always_on: bool = False
	idle_time_for_shutdown: Optional[int]

	@validator('idle_time_for_shutdown')
	def validate_idle_time_for_shutdown(cls, v):
		if v < 5:
			raise ValueError(f'idle_time_for_shutdown must be at least 5, was {v}')
		return v

	@root_validator
	def validate(cls, values):
		if values.get('always_on') and values.get('idle_time_for_shutdown', None):
			raise ValueError('if always_on is true, idle_time_for_shutdown must not be set')
		if not values.get('always_on') and not values.get('idle_time_for_shutdown', None):
			raise ValueError('if always_on is false or not set, idle_time_for_shutdown must be set')
		return values


class App(BaseModel):
	v: str
	name: str
	image: str
	entrypoints: List[Entrypoint]
	data_dirs: Optional[List[Union[str, DataDir]]]
	env_vars: Optional[Dict[str, str]]
	services: Optional[List[Service]]
	paths: Dict[str, Path]
	lifecycle: Lifecycle = Lifecycle(idle_time_for_shutdown=60)
	store_info: Optional[StoreInfo]

	@root_validator(pre=True)
	def migrate(cls, values):
		if 'v' not in values:
			values['v'] = '0.0'
		while values['v'] != CURRENT_VERSION:
			migrate = app_migration.migrations[values['v']]
			values = migrate(values)
		return values


class AppToInstall(App):
	installation_reason: InstallationReason = InstallationReason.UNKNOWN


class InstalledApp(AppToInstall):
	status: str = Status.UNKNOWN
	postgres: Union[Postgres, None]
