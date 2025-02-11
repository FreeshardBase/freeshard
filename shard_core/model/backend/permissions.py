# DO NOT MODIFY - copied from portal_controller

from enum import StrEnum, auto
from typing import List

from pydantic import BaseModel


class Permission(StrEnum):
	LIST_PORTALS = auto()
	READ_PORTAL = auto()
	MODIFY_PORTAL = auto()
	DELETE_PORTAL = auto()
	READ_REVENUE_SHARE = auto()
	MODIFY_REVENUE_SHARE = auto()
	ISSUE_BACKUP_RESTORE_TOKEN = auto()


class PermissionHolder(BaseModel):
	permissions: List[Permission] | None = []
