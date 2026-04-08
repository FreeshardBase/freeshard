# DO NOT MODIFY - copied from freeshard-controller

from datetime import datetime
from enum import StrEnum, auto
from functools import total_ordering
from typing import List

from pydantic import BaseModel

from .permission_model import PermissionHolder
from .telemetry_model import Telemetry


class ShardStatus(StrEnum):
    CREATING = auto()
    BLANK = auto()
    PREPARING = auto()
    PREPARED = auto()
    IMAGING = auto()
    STOPPING = auto()
    STOPPED = auto()
    STARTING = auto()
    STANDBY = auto()
    ASSIGNED = auto()
    DELETING = auto()
    EXPANDING_VOLUME = auto()
    UPGRADING = auto()
    RESIZING = auto()
    ERROR = auto()


_VM_SIZE_ORDER = ["xs", "s", "m", "l", "xl"]


@total_ordering
class VmSize(StrEnum):
    XS = auto()
    S = auto()
    M = auto()
    L = auto()
    XL = auto()

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, VmSize):
            return NotImplemented
        return _VM_SIZE_ORDER.index(self.value) < _VM_SIZE_ORDER.index(other.value)

    def __eq__(self, other: object) -> bool:
        return str.__eq__(self, other)

    def __hash__(self) -> int:
        return str.__hash__(self)


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
    volume_size_gb: int | None = None
    auto_managed: bool = True
    core_version: str | None = None
    last_seen_backup: datetime | None = None

    @property
    def short_id(self) -> str:
        return self.hash_id[:6]


class ShardDb(ShardBase):
    id: int


class ShardResponse(ShardDb):
    telemetry: List[Telemetry]


class ShardUpdate(BaseModel):
    owner_name: str | None = None
    max_vm_size: VmSize | None = None
    delete_after: datetime | None = None
    status: ShardStatus | None = None


class ShardCreateDb(BaseModel):
    machine_id: str | None
    status: ShardStatus
    vm_size: VmSize
    time_created: datetime
    delete_after: datetime | None = None
    cloud: Cloud
    auto_managed: bool = True


class ShardUpdateDb(BaseModel):
    machine_id: str | None = None
    hash_id: str | None = None
    domain: str | None = None
    address: str | None = None
    owner_name: str | None = None
    owner_email: str | None = None
    vm_size: VmSize | None = None
    max_vm_size: VmSize | None = None
    expiration_warning_24h_sent: datetime | None = None
    expiration_warning_1h_sent: datetime | None = None
    delete_after: datetime | None = None
    public_key_pem: str | None = None
    status: ShardStatus | None = None
    volume_id: str | None = None
    volume_size_gb: int | None = None
    time_assigned: datetime | None = None
    core_version: str | None = None
    last_seen_backup: datetime | None = None


class AppUsageReport(BaseModel):
    id: int
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


class CoreUpdateRequest(BaseModel):
    target_version: str


class RollbackRequest(BaseModel):
    target_version: str


class ExpandVolumeRequest(BaseModel):
    new_size_gb: int


class ResizeRequest(BaseModel):
    new_vm_size: VmSize


class AddPubkeyRequest(BaseModel):
    pubkey: str


class InvalidShardStatus(Exception):
    pass


class ShardLifecycleEventDb(BaseModel):
    id: int
    shard_id: int
    timestamp: datetime
    status_to: ShardStatus
    actor: str
    details: str | None = None
    error_message: str | None = None
    error_traceback: str | None = None


class ShardLifecycleEventResponse(BaseModel):
    id: int
    shard_id: int
    timestamp: datetime
    status_to: ShardStatus
    actor: str
    details: str | None = None
    error_message: str | None = None
    error_traceback: str | None = None
