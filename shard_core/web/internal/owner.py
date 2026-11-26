from fastapi import APIRouter, HTTPException, status

from shard_core.data_model.user import OutputOwner
from shard_core.database import users as db_users
from shard_core.database.connection import db_conn

router = APIRouter()


@router.get("/owner", response_model=OutputOwner)
async def get_owner():
    async with db_conn() as conn:
        owner = await db_users.get_owner(conn)
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return owner
