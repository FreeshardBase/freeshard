import logging
from enum import Enum
from typing import List

from fastapi import APIRouter, status, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from shard_core.database import db_methods

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
def put_tour(tour: Tour):
    tour_dict = tour.dict()
    tour_dict['id'] = tour.name
    tour_dict['completed'] = (tour.status == TourStatus.SEEN)
    db_methods.insert_tour(tour_dict)


@tour_router.get("/{name}", response_model=Tour)
def get_tour(name: str):
    tour_data = db_methods.get_tour_by_id(name)
    if tour_data:
        return Tour(
            name=tour_data['id'],
            status=TourStatus.SEEN if tour_data.get('completed') else TourStatus.UNSEEN
        )
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@tour_router.get("", response_model=List[Tour])
def list_tours():
    all_tours = db_methods.get_all_tours()
    return [
        Tour(
            name=t['id'],
            status=TourStatus.SEEN if t.get('completed') else TourStatus.UNSEEN
        )
        for t in all_tours
    ]


@tour_router.delete("", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def reset_tours():
    db_methods.delete_all_tours()


router.include_router(tour_router)
