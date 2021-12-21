from fastapi import APIRouter

from . import apps, store

router = APIRouter(
	prefix='/protected',
	tags=['/protected'],
)

router.include_router(apps.router)
router.include_router(store.router)
