from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class Role(str, Enum):
    # Keep in sync with the user_role enum in migrations/shard-core-0002-users.sql
    OWNER = "owner"
    MEMBER = "member"


class User(BaseModel):
    id: int
    username: str
    display_name: str
    email: Optional[str] = None
    role: Role = Role.MEMBER
    disabled: bool = False
    created: Optional[datetime] = None

    def __str__(self):
        return f"User[{self.id}, {self.username}]"
