from enum import Enum
from typing import Optional, List, Dict, Union

from pydantic import BaseModel, root_validator

from portal_core.model import app_migration


class InstallationReason(str, Enum):
	UNKNOWN = 'unknown'
	CONFIG = 'config'
	CUSTOM = 'custom'
	STORE = 'store'


class Access(str, Enum):
	PUBLIC = 'public'
	PRIVATE = 'private'


class Status(str, Enum):
	UNKNOWN = 'unknown'
	RUNNING = 'running'


class Service(str, Enum):
	POSTGRES = 'postgres'


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
	uid: int
	gid: int


class Path(BaseModel):
	access: Access
	headers: Optional[Dict[str, str]]


class App(BaseModel):
	v: str
	name: str
	description: str = 'n/a'
	image: str
	port: int
	data_dirs: Optional[List[Union[str, DataDir]]]
	env_vars: Optional[Dict[str, str]]
	services: Optional[List[Service]]
	paths: Dict[str, Path]

	@root_validator(pre=True)
	def migrate(cls, values):
		if 'v' not in values:
			values['v'] = '0.0'
		while values['v'] != '1.0':
			migrate = app_migration.migrations[values['v']]
			values = migrate(values)
		return values


class AppToInstall(App):
	installation_reason: InstallationReason = InstallationReason.UNKNOWN


class InstalledApp(AppToInstall):
	status: str = Status.UNKNOWN
	postgres: Union[Postgres, None]


class StoreApp(App):
	is_installed: bool


class StoreAppOverview(BaseModel):
	name: str
	description: str
	is_installed: bool
