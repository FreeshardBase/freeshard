import logging
from enum import Enum
from typing import List

from fastapi import APIRouter, status, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from shard_core.database.connection import db_conn
from shard_core.database import tours as tours_db

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/help",
)

tour_router = APIRouter(prefix="/tours")


class TourStatus(str, Enum):
    SEEN = "seen"
    UNSEEN = "unseen"


class Tour(BaseModel):
    name: str
    status: TourStatus


@tour_router.put("", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def put_tour(tour: Tour):
    async with db_conn() as conn:
        await tours_db.upsert(conn, tour.dict())


@tour_router.get("/{name}", response_model=Tour)
async def get_tour(name: str):
    async with db_conn() as conn:
        tour = await tours_db.get_by_name(conn, name)
    if tour:
        return Tour(**tour)
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@tour_router.get("", response_model=List[Tour])
async def list_tours():
    async with db_conn() as conn:
        all_tours = await tours_db.get_all(conn)
    return [Tour(**t) for t in all_tours]


@tour_router.delete("", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def reset_tours():
    async with db_conn() as conn:
        await tours_db.truncate(conn)


router.include_router(tour_router)
