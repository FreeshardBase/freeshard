import datetime
from enum import Enum
from pathlib import Path as FilePath
from typing import Optional, List, Dict, Union

import gconf
from pydantic import BaseModel, root_validator, validator

from shard_core.db import installed_apps
from shard_core.data_model import app_meta_migration
from shard_core.util import signals

CURRENT_VERSION = "1.2"


class InstallationReason(str, Enum):
    UNKNOWN = "unknown"
    CONFIG = "config"
    CUSTOM = "custom"
    STORE = "store"


class Access(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    PEER = "peer"


class Status(str, Enum):
    UNKNOWN = "unknown"
    INSTALLATION_QUEUED = "installation_queued"
    INSTALLING = "installing"
    STOPPED = "stopped"
    RUNNING = "running"
    UNINSTALLATION_QUEUED = "uninstallation_queued"
    UNINSTALLING = "uninstalling"
    REINSTALLATION_QUEUED = "reinstallation_queued"
    REINSTALLING = "reinstalling"
    DOWN = "down"
    ERROR = "error"


class EntrypointPort(str, Enum):
    HTTPS_443 = "http"
    MQTTS_1883 = "mqtt"


# todo: use data_model.backend.shard_model.VmSize - add comparison methods to it
class VMSize(str, Enum):
    XS = "xs"
    S = "s"
    M = "m"
    L = "l"
    XL = "xl"

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
    description_short: Optional[str]
    description_long: Optional[Union[str, List[str]]]
    hint: Optional[Union[str, List[str]]]
    is_featured: Optional[bool]


class Path(BaseModel):
    access: Access
    headers: Optional[Dict[str, str]]


class Entrypoint(BaseModel):
    container_name: str
    container_port: int
    entrypoint_port: EntrypointPort


class Lifecycle(BaseModel):
    always_on: bool = False
    idle_time_for_shutdown: Optional[int]

    @validator("idle_time_for_shutdown")
    def validate_idle_time_for_shutdown(cls, v):
        if v and v < 5:
            raise ValueError(f"idle_time_for_shutdown must be at least 5, was {v}")
        return v

    @root_validator
    def validate_exclusivity(cls, values):
        if values.get("always_on") and values.get("idle_time_for_shutdown", None):
            raise ValueError(
                "if always_on is true, idle_time_for_shutdown must not be set"
            )
        if not values.get("always_on") and not values.get(
            "idle_time_for_shutdown", None
        ):
            raise ValueError(
                "if always_on is false or not set, idle_time_for_shutdown must be set"
            )
        return values


class AppMeta(BaseModel):
    v: str
    app_version: str
    upstream_repo: str | None
    homepage: str | None
    name: str
    pretty_name: str
    icon: str
    entrypoints: List[Entrypoint]
    paths: Dict[str, Path]
    lifecycle: Lifecycle = Lifecycle(idle_time_for_shutdown=60)
    minimum_portal_size: VMSize = VMSize.XS
    store_info: Optional[StoreInfo]

    @root_validator(pre=True)
    def migrate(cls, values):
        migration_count = 0
        while values["v"] != CURRENT_VERSION:
            if migration_count > len(app_meta_migration.migrations):
                raise Exception(
                    "migration seems to be stuck, perhaps a migration does not increment the version number?"
                )
            migrate = app_meta_migration.migrations[values["v"]]
            values = migrate(values)
            migration_count += 1
        return values


class InstalledApp(BaseModel):
    # database model
    name: str
    installation_reason: InstallationReason = InstallationReason.UNKNOWN
    status: str = Status.UNKNOWN
    last_access: Optional[datetime.datetime] = None


class InstalledAppWithMeta(InstalledApp):
    meta: AppMeta | None


@signals.on_request_to_app.connect
def update_last_access(app: InstalledApp):
    now = datetime.datetime.utcnow()
    max_update_frequency = datetime.timedelta(
        seconds=gconf.get("apps.last_access.max_update_frequency")
    )
    if app.last_access and now - app.last_access < max_update_frequency:
        return
    installed_apps.update(app.name, last_access=now)


if __name__ == "__main__":
    dest_dir = FilePath("schemas")
    dest_dir.mkdir(exist_ok=True)
    with open(dest_dir / f"schema_app_meta_{CURRENT_VERSION}.json", "w") as f:
        f.write(AppMeta.schema_json(indent=2))
