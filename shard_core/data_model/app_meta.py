import datetime
import json
from enum import Enum
from pathlib import Path as FilePath
from typing import Optional, List, Dict, Union

from pydantic import BaseModel, model_validator

from shard_core.data_model import app_meta_migration
from shard_core.settings import settings
from shard_core.util import signals

CURRENT_VERSION = "1.3"


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
    PAUSED = "paused"
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
    description_short: Optional[str] = None
    description_long: Optional[Union[str, List[str]]] = None
    hint: Optional[Union[str, List[str]]] = None
    is_featured: Optional[bool] = None


class Path(BaseModel):
    access: Access
    headers: Optional[Dict[str, str]] = None


class Entrypoint(BaseModel):
    container_name: str
    container_port: int
    entrypoint_port: EntrypointPort


class Lifecycle(BaseModel):
    always_on: bool = False
    skip_pause: bool = False
    idle_for_pause: int | None = None  # None = use global default
    idle_for_stop: int | None = None  # None = use global default

    @model_validator(mode="after")
    def validate_combinations(self):
        if self.always_on and (
            self.skip_pause
            or self.idle_for_pause is not None
            or self.idle_for_stop is not None
        ):
            raise ValueError(
                "if always_on is true, no other lifecycle field may be set"
            )
        if self.skip_pause and self.idle_for_pause is not None:
            raise ValueError("skip_pause and idle_for_pause are mutually exclusive")
        if self.idle_for_pause is not None and self.idle_for_pause < 5:
            raise ValueError(
                f"idle_for_pause must be at least 5, was {self.idle_for_pause}"
            )
        if self.idle_for_stop is not None and self.idle_for_stop < 5:
            raise ValueError(
                f"idle_for_stop must be at least 5, was {self.idle_for_stop}"
            )
        if (
            self.idle_for_pause is not None
            and self.idle_for_stop is not None
            and self.idle_for_pause >= self.idle_for_stop
        ):
            raise ValueError("idle_for_pause must be less than idle_for_stop")
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
    lifecycle: Lifecycle = Lifecycle()
    minimum_portal_size: VMSize = VMSize.XS
    store_info: Optional[StoreInfo] = None

    @model_validator(mode="before")
    @classmethod
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
async def update_last_access(app: InstalledApp):
    now = datetime.datetime.now(datetime.timezone.utc)
    max_update_frequency = datetime.timedelta(
        seconds=settings().apps.last_access.max_update_frequency
    )
    if app.last_access and now - app.last_access < max_update_frequency:
        return
    from shard_core.database.connection import db_conn
    from shard_core.database import installed_apps as db_installed_apps

    async with db_conn() as conn:
        await db_installed_apps.update_last_access(conn, app.name, now)
    app.last_access = now


if __name__ == "__main__":
    dest_dir = FilePath("schemas")
    dest_dir.mkdir(exist_ok=True)
    with open(dest_dir / f"schema_app_meta_{CURRENT_VERSION}.json", "w") as f:
        f.write(json.dumps(AppMeta.model_json_schema(), indent=2))
