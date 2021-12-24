from fastapi import APIRouter

from . import health, pair

router = APIRouter(
	prefix='/public',
	tags=['/public'],
)

router.include_router(health.router)
router.include_router(pair.router)
