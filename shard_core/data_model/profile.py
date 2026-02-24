from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from shard_core.data_model.backend.shard_model import ShardBase
from shard_core.db import key_value
from shard_core.db.db_connection import db_conn
from shard_core.data_model.app_meta import VMSize


class Profile(BaseModel):
    vm_id: str
    owner: Optional[str]
    owner_email: Optional[str]
    time_created: datetime
    time_assigned: Optional[datetime]
    delete_after: Optional[datetime] = None
    vm_size: VMSize
    max_vm_size: Optional[VMSize]

    @classmethod
    def from_shard(cls, shard: ShardBase):
        return cls(
            vm_id=shard.machine_id,
            owner=shard.owner_name,
            owner_email=shard.owner_email,
            time_created=shard.time_created,
            time_assigned=shard.time_assigned,
            delete_after=shard.delete_after,
            vm_size=VMSize(shard.vm_size.value.lower()),
            max_vm_size=(
                VMSize(shard.max_vm_size.value.lower()) if shard.max_vm_size else None
            ),
        )


async def set_profile(profile: Profile | None):
    async with db_conn() as conn:
        await key_value.set(conn, "profile", profile.dict() if profile else "None")


async def get_profile() -> Profile | None:
    async with db_conn() as conn:
        try:
            value = await key_value.get(conn, "profile")
            return None if value == "None" else Profile.parse_obj(value)
        except KeyError:
            return None
