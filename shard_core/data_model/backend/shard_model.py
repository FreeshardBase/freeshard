# DO NOT MODIFY - copied from freeshard-controller

from datetime import datetime
from enum import StrEnum, auto
from typing import List

from pydantic import BaseModel

from .permission_model import PermissionHolder
from .subscription_model import SubscriptionStatus
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


class VmSize(StrEnum):
    XS = auto()
    S = auto()
    M = auto()
    L = auto()
    XL = auto()

    def _idx(self) -> int:
        return _VM_SIZE_ORDER.index(self.value)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, VmSize):
            return NotImplemented
        return self._idx() < other._idx()

    def __le__(self, other: object) -> bool:
        if not isinstance(other, VmSize):
            return NotImplemented
        return self._idx() <= other._idx()

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, VmSize):
            return NotImplemented
        return self._idx() > other._idx()

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, VmSize):
            return NotImplemented
        return self._idx() >= other._idx()

    def __eq__(self, other: object) -> bool:
        return str.__eq__(self, other)

    def __hash__(self) -> int:
        return str.__hash__(self)


class Cloud(StrEnum):
    DEFAULT = auto()
    AZURE = auto()
    OVHCLOUD = auto()


class ShardBase(BaseModel):
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
    subscription_id: int | None = None
    price_cents: int | None = None
    pending_vm_size: VmSize | None = None
    pending_price_cents: int | None = None

    @property
    def short_id(self) -> str:
        return self.hash_id[:6]


class ShardDb(ShardBase):
    id: int


class ShardWithPermissions(ShardDb, PermissionHolder):
    """ShardDb enriched with permissions loaded from the DB."""

    pass


class ShardSubscriptionSummary(BaseModel):
    status: SubscriptionStatus
    price_cents: int
    currency: str
    next_billing_date: datetime | None = None
    last_payment_failed_at: datetime | None = None
    ended: datetime | None = None
    payer_email: str | None = None
    pending_vm_size: VmSize | None = None
    pending_price_cents: int | None = None
    paypal_manage_url: str


class ShardResponse(ShardWithPermissions):
    telemetry: List[Telemetry]
    telemetry_start: datetime
    telemetry_end: datetime
    subscription: ShardSubscriptionSummary | None = None
    billing_enabled: bool = False
    paypal_client_id: str | None = None
    paypal_environment: str | None = None  # "sandbox" | "live"


class ShardUpdate(BaseModel):
    owner_name: str | None = None
    max_vm_size: VmSize | None = None
    delete_after: datetime | None = None
    status: ShardStatus | None = None
    core_version: str | None = None


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
    subscription_id: int | None = None
    price_cents: int | None = None
    pending_vm_size: VmSize | None = None
    pending_price_cents: int | None = None


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


class AssignTrialRequest(BaseModel):
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


class BulkUpgradeCoreRequest(BaseModel):
    shard_ids: list[int]


class BulkUpgradeCoreResponse(BaseModel):
    upgraded: int
    skipped: int


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


class ShardLifecycleEventResponse(ShardLifecycleEventDb):
    actor_owner_name: str | None = None
    actor_db_id: int | None = None
