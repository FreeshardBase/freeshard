# DO NOT MODIFY - copied from portal_controller

from datetime import datetime
from typing import Set

from pydantic import BaseModel

from .permissions import Permission, PermissionHolder


class ApiToken(PermissionHolder, BaseModel):
	id: str
	name: str
	owner_portal_id: str
	created: datetime
	token: str


class ApiTokenCreate(BaseModel):
	name: str
	permissions: Set[Permission]
