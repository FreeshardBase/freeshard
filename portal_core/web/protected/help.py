import logging
from typing import List

from fastapi import APIRouter, status, HTTPException
from fastapi.responses import Response
from sqlalchemy.exc import NoResultFound
from sqlmodel import select, delete

from portal_core.database.database import session
from portal_core.database.models import Tour

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/help',
)

tour_router = APIRouter(
	prefix='/tours'
)


@tour_router.put('', status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def put_tour(tour: Tour):
	with session() as session_:
		session_.merge(tour)
		session_.commit()


@tour_router.get('/{name}', response_model=Tour)
def get_tour(name: str):
	with session() as session_:
		try:
			return session_.exec(select(Tour).where(Tour.name == name)).one()
		except NoResultFound:
			raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@tour_router.get('', response_model=List[Tour])
def list_tours():
	with session() as session_:
		tours = session_.exec(select(Tour)).all()
		return tours


@tour_router.delete('', status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def reset_tours():
	with session() as session_:
		session_.exec(delete(Tour))
		session_.commit()


router.include_router(tour_router)
