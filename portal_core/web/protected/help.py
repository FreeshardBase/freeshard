import logging
from enum import Enum
from typing import List

from fastapi import APIRouter, status, HTTPException
from pydantic import BaseModel
from tinydb import Query
from tinydb.table import Table

from portal_core.database.database import tours_table

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/help',
)

tour_router = APIRouter(
	prefix='/tours'
)


class TourStatus(str, Enum):
	SEEN = 'seen'
	UNSEEN = 'unseen'


class Tour(BaseModel):
	name: str
	status: TourStatus


@tour_router.put('', status_code=status.HTTP_204_NO_CONTENT)
def put_tour(tour: Tour):
	with tours_table() as tours:  # type: Table
		tours.upsert(tour.dict(), Query().name == tour.name)


@tour_router.get('/{name}', response_model=Tour)
def get_tour(name: str):
	with tours_table() as tours:  # type: Table
		if tour := tours.get(Query().name == name):
			return Tour(**tour)
		else:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@tour_router.get('', response_model=List[Tour])
def list_tours():
	with tours_table() as tours:  # type: Table
		return [Tour(**t) for t in tours]


@tour_router.delete('', status_code=status.HTTP_204_NO_CONTENT)
def reset_tours():
	with tours_table() as tours:  # type: Table
		tours.truncate()


router.include_router(tour_router)
