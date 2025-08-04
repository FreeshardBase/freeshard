from fastapi import APIRouter

from . import health, meta, pair

router = APIRouter(
    prefix="/public",
    tags=["/public"],
)

router.include_router(health.router)
router.include_router(meta.router)
router.include_router(pair.router)
