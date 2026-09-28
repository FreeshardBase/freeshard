# DO NOT MODIFY - copied from freeshard-controller

from datetime import datetime
from enum import StrEnum, auto

from pydantic import BaseModel

from .shard_model import Cloud


# Mirrors the SQL type `shard_migration_status` in migration 0030. The two must be
# edited together, and a new label needs its own migration file because Postgres
# refuses to use an enum label in the transaction that added it.
class ShardMigrationStatus(StrEnum):
    PREPARING_TARGET = auto()
    TARGET_PREPARED = auto()
    SYNCING = auto()
    CUTTING_OVER = auto()
    COMPLETED = auto()
    ROLLED_BACK = auto()
    ERROR = auto()


# A shard may have only one migration in one of these at a time, enforced by the partial
# unique index in migration 0030. Keep the two in sync.
LIVE_MIGRATION_STATUSES = frozenset(
    {
        ShardMigrationStatus.PREPARING_TARGET,
        ShardMigrationStatus.TARGET_PREPARED,
        ShardMigrationStatus.SYNCING,
        ShardMigrationStatus.CUTTING_OVER,
    }
)


class ShardMigrationDb(BaseModel):
    id: int
    shard_id: int
    status: ShardMigrationStatus
    created_at: datetime
    source_cloud: Cloud
    source_machine_id: str
    source_volume_id: str | None = None
    target_cloud: Cloud
    target_machine_id: str | None = None
    target_volume_id: str | None = None
    target_volume_size_gb: int
    core_version: str
    last_sync_started_at: datetime | None = None
    last_sync_finished_at: datetime | None = None
    last_sync_exit_status: int | None = None
    last_sync_bytes: int | None = None
    sync_progress_bytes: int | None = None
    sync_progress_percent: float | None = None
    sync_progress_at: datetime | None = None
    cut_over_at: datetime | None = None
    source_deleted_at: datetime | None = None
    error_message: str | None = None
    error_traceback: str | None = None


class ShardMigrationCreateDb(BaseModel):
    shard_id: int
    status: ShardMigrationStatus
    source_cloud: Cloud
    source_machine_id: str
    source_volume_id: str | None = None
    target_cloud: Cloud
    target_volume_size_gb: int
    core_version: str


class ShardMigrationUpdateDb(BaseModel):
    status: ShardMigrationStatus | None = None
    target_machine_id: str | None = None
    target_volume_id: str | None = None
    last_sync_started_at: datetime | None = None
    last_sync_finished_at: datetime | None = None
    last_sync_exit_status: int | None = None
    last_sync_bytes: int | None = None
    sync_progress_bytes: int | None = None
    sync_progress_percent: float | None = None
    sync_progress_at: datetime | None = None
    cut_over_at: datetime | None = None
    source_deleted_at: datetime | None = None
    error_message: str | None = None
    error_traceback: str | None = None


class MigrateShardRequest(BaseModel):
    target_cloud: Cloud


class MigrationAlreadyInFlight(Exception):
    pass


class MigrationNotPossible(Exception):
    pass


class ShardHasLiveMigration(Exception):
    pass


class ShardHasSurvivingMigrationSource(Exception):
    pass


class InvalidMigrationStatus(Exception):
    pass


class MigrationVerificationFailed(Exception):
    pass
