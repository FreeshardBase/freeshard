# DO NOT MODIFY - copied from portal_controller

from enum import StrEnum, auto
from typing import List

from pydantic import BaseModel


class Permission(StrEnum):
	LIST_PORTALS = auto()
	READ_PORTAL = auto()
	MODIFY_PORTAL = auto()
	DELETE_PORTAL = auto()


class PermissionHolder(BaseModel):
	permissions: List[Permission] | None = []
