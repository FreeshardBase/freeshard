# DO NOT MODIFY - copied from freeshard-controller

from enum import StrEnum, auto
from typing import Set

from pydantic import BaseModel, Field


# noinspection PyEnum
class Permission(StrEnum):
    LIST_SHARDS = auto()
    READ_SHARD = auto()
    MODIFY_SHARD = auto()
    DELETE_SHARD = auto()
    READ_REVENUE_SHARE = auto()
    MODIFY_REVENUE_SHARE = auto()
    ISSUE_BACKUP_RESTORE_TOKEN = auto()
    CREATE_PROMO_CODE = auto()
    MODIFY_PROMO_CODE = auto()


class PermissionHolder(BaseModel):
    permissions: Set[Permission] = Field(default_factory=set)
