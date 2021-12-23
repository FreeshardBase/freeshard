from fastapi import APIRouter

from . import apps, identities, store, peers

router = APIRouter(
	prefix='/protected',
	tags=['/protected'],
)

router.include_router(apps.router)
router.include_router(identities.router)
router.include_router(store.router)
router.include_router(peers.router)
