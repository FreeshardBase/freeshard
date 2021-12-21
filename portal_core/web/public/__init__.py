from fastapi import APIRouter

from . import health

router = APIRouter(
	prefix='/public',
	tags=['/public'],
)

router.include_router(health.router)
