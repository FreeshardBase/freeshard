# DO NOT MODIFY - copied from freeshard-controller

from datetime import datetime
from enum import StrEnum, auto

from pydantic import BaseModel

from .permission_model import PermissionHolder


class ShardStatus(StrEnum):
    CREATING = auto()
    BLANK = auto()
    PREPARING = auto()
    PREPARED = auto()
    STOPPING = auto()
    STOPPED = auto()
    STARTING = auto()
    STANDBY = auto()
    ASSIGNED = auto()
    DELETING = auto()
    ERROR = auto()


class VmSize(StrEnum):
    XS = auto()
    S = auto()
    M = auto()
    L = auto()
    XL = auto()


class Cloud(StrEnum):
    DEFAULT = auto()
    AZURE = auto()
    OVHCLOUD = auto()


class ShardBase(PermissionHolder, BaseModel):
    machine_id: str | None
    hash_id: str | None = None
    domain: str | None = None
    address: str | None = None
    public_key_pem: str | None = None
    status: ShardStatus
    owner_name: str | None = None
    owner_email: str | None = None
    vm_size: VmSize
    max_vm_size: VmSize | None = None
    time_created: datetime
    time_assigned: datetime | None = None
    expiration_warning_24h_sent: datetime | None = None
    expiration_warning_1h_sent: datetime | None = None
    delete_after: datetime | None = None
    shared_secret: str | None = None
    cloud: Cloud
    volume_id: str | None = None

    @property
    def short_id(self) -> str:
        return self.hash_id[:6]


class ShardDb(ShardBase):
    id: int


class ShardUpdate(BaseModel):
    owner: str | None = None
    max_size: VmSize | None = None
    delete_after: datetime | None = None


class ShardCreateDb(BaseModel):
    machine_id: str | None
    status: ShardStatus
    vm_size: VmSize
    time_created: datetime
    delete_after: datetime | None = None
    cloud: Cloud


class ShardUpdateDb(BaseModel):
    machine_id: str | None = None
    hash_id: str | None = None
    domain: str | None = None
    address: str | None = None
    owner_name: str | None = None
    owner_email: str | None = None
    max_size: VmSize | None = None
    expiration_warning_24h_sent: datetime | None = None
    expiration_warning_1h_sent: datetime | None = None
    delete_after: datetime | None = None
    public_key_pem: str | None = None
    status: ShardStatus | None = None
    volume_id: str | None = None


class AppUsageReport(BaseModel):
    id: str
    shard_id: str
    year: int
    month: int
    usage: dict[str, int]
    assigned_amount: int | None = None


class AppUsageReportUpdate(BaseModel):
    assigned_amount: int | None = None


class SasUrlResponse(BaseModel):
    sas_url: str
    container_name: str


class AssignShardRequest(BaseModel):
    promo_code: str | None = None
    owner_name: str | None = None
    owner_email: str | None = None


class AssignShardResponse(BaseModel):
    hash_id: str
    domain: str
    code: str
    created: datetime
    valid_until: datetime


class PairingCodeResponse(BaseModel):
    code: str
    created: datetime
    valid_until: datetime


class InvalidShardStatus(Exception):
    pass
