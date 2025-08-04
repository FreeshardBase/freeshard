# DO NOT MODIFY - copied from freeshard-controller

from datetime import datetime
from typing import Set

from pydantic import BaseModel

from .permission_model import PermissionHolder, Permission


class ApiTokenResult(PermissionHolder, BaseModel):
    id: int
    name: str
    created: datetime
    token: str
    owner_hash_id: str
    owner_name: str


class ApiTokenCreate(BaseModel):
    name: str
    permissions: Set[Permission]
