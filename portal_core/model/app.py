from enum import Enum
from typing import Optional, List, Dict, Union

from pydantic import BaseModel


class InstallationReason(str, Enum):
	UNKNOWN = 'unknown'
	CONFIG = 'config'
	CUSTOM = 'custom'
	STORE = 'store'


class DefaultAccess(str, Enum):
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


class Authentication(BaseModel):
	default_access: DefaultAccess = DefaultAccess.PRIVATE
	public_paths: Optional[List[str]]
	private_paths: Optional[List[str]]
	peer_paths: Optional[List[str]]


class App(BaseModel):
	name: str
	description: str = 'n/a'
	image: str
	port: int
	data_dirs: Optional[List[Union[str, DataDir]]]
	env_vars: Optional[Dict[str, str]]
	services: Optional[List[Service]]
	authentication: Optional[Authentication]


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
