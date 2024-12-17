import datetime
import json
from enum import Enum
from pathlib import Path as FilePath
from typing import Optional, List, Dict, Self

import gconf
from pydantic import BaseModel, field_validator, model_validator
from sqlmodel import select

from portal_core.database.database import session
from portal_core.database.models import InstalledApp, InstallationReason
from portal_core.model import app_meta_migration
from portal_core.util import signals

CURRENT_VERSION = '1.2'


class Access(str, Enum):
	PUBLIC = 'public'
	PRIVATE = 'private'
	PEER = 'peer'


class EntrypointPort(str, Enum):
	HTTPS_443 = 'http'
	MQTTS_1883 = 'mqtt'


class PortalSize(str, Enum):
	XS = 'xs'
	S = 's'
	M = 'm'
	L = 'l'
	XL = 'xl'

	def _index(self):
		return list(self.__class__.__members__.values()).index(self)

	def __gt__(self, other):
		return self._index() > other._index()

	def __ge__(self, other):
		return self._index() >= other._index()

	def __lt__(self, other):
		return self._index() < other._index()

	def __le__(self, other):
		return self._index() <= other._index()


class StoreInfo(BaseModel):
	description_short: str | None = None
	description_long: str | List[str] | None = None
	hint: str | List[str] | None = None
	is_featured: bool = False


class Path(BaseModel):
	access: Access
	headers: Optional[Dict[str, str]]


class Entrypoint(BaseModel):
	container_name: str
	container_port: int
	entrypoint_port: EntrypointPort


class Lifecycle(BaseModel):
	always_on: bool = False
	idle_time_for_shutdown: int | None = None

	@field_validator('idle_time_for_shutdown')
	def validate_idle_time_for_shutdown(cls, v):
		if v and v < 5:
			raise ValueError(f'idle_time_for_shutdown must be at least 5, was {v}')
		return v

	@model_validator(mode='after')
	def validate_exclusivity(self) -> Self:
		if self.always_on and self.idle_time_for_shutdown:
			raise ValueError('if always_on is true, idle_time_for_shutdown must not be set')
		if not self.always_on and not self.idle_time_for_shutdown:
			raise ValueError('if always_on is false or not set, idle_time_for_shutdown must be set')
		return self


class AppMeta(BaseModel):
	v: str
	app_version: str
	upstream_repo: str | None = None
	homepage: str | None = None
	name: str
	pretty_name: str
	icon: str
	entrypoints: List[Entrypoint]
	paths: Dict[str, Path]
	lifecycle: Lifecycle = Lifecycle(idle_time_for_shutdown=60)
	minimum_portal_size: PortalSize = PortalSize.XS
	store_info: Optional[StoreInfo]

	@model_validator(mode='before')
	def migrate(cls, values):
		migration_count = 0
		while values['v'] != CURRENT_VERSION:
			if migration_count > len(app_meta_migration.migrations):
				raise Exception(
					'migration seems to be stuck, perhaps a migration does not increment the version number?')
			migrate = app_meta_migration.migrations[values['v']]
			values = migrate(values)
			migration_count += 1
		return values


class InstalledAppWithMeta(BaseModel):
	name: str
	installation_reason: InstallationReason
	status: str
	last_access: datetime.datetime | None = None
	meta: AppMeta | None


@signals.on_request_to_app.connect
def update_last_access(app: InstalledApp):
	now = datetime.datetime.now(datetime.timezone.utc)
	max_update_frequency = datetime.timedelta(seconds=gconf.get('apps.last_access.max_update_frequency'))
	if app.last_access and now - app.last_access < max_update_frequency:
		return
	with session() as session_:
		app_db = session_.exec(select(InstalledApp).where(InstalledApp.name == app.name)).one()
		app_db.last_access = now
		session_.add(app_db)
		session_.commit()


if __name__ == '__main__':
	dest_dir = FilePath('schemas')
	dest_dir.mkdir(exist_ok=True)
	with open(dest_dir / f'schema_app_meta_{CURRENT_VERSION}.json', 'w') as f:
		f.write(json.dumps(AppMeta.model_json_schema(), indent=2))
