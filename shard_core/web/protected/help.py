import logging
from enum import Enum
from typing import List

from fastapi import APIRouter, status, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from shard_core.db import tours
from shard_core.db.db_connection import db_conn

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
    tour_dict = tour.dict()
    tour_dict['id'] = tour.name
    tour_dict['completed'] = (tour.status == TourStatus.SEEN)
    async with db_conn() as conn:
        await tours.insert(conn, tour_dict)


@tour_router.get("/{name}", response_model=Tour)
async def get_tour(name: str):
    async with db_conn() as conn:
        tour_data = await tours.get_by_id(conn, name)
    if tour_data:
        return Tour(
            name=tour_data['id'],
            status=TourStatus.SEEN if tour_data.get('completed') else TourStatus.UNSEEN
        )
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@tour_router.get("", response_model=List[Tour])
async def list_tours():
    async with db_conn() as conn:
        all_tours = await tours.get_all(conn)
    return [
        Tour(
            name=t['id'],
            status=TourStatus.SEEN if t.get('completed') else TourStatus.UNSEEN
        )
        for t in all_tours
    ]


@tour_router.delete("", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def reset_tours():
    async with db_conn() as conn:
        await tours.delete_all(conn)


router.include_router(tour_router)
