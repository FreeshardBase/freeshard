from enum import Enum
from typing import Optional, List, Dict

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
	data_dirs: Optional[List[str]]
	env_vars: Optional[Dict[str, str]]
	authentication: Optional[Authentication]


class AppToInstall(App):
	installation_reason: InstallationReason = InstallationReason.UNKNOWN


class InstalledApp(AppToInstall):
	status: str = Status.UNKNOWN


class StoreApp(App):
	is_installed: bool


class StoreAppOverview(BaseModel):
	name: str
	description: str
	is_installed: bool

