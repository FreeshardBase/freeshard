from fastapi import APIRouter

from . import health, meta, oidc, pair, users

router = APIRouter(
    prefix="/public",
    tags=["/public"],
)

router.include_router(health.router)
router.include_router(meta.router)
router.include_router(oidc.router)
router.include_router(pair.router)
router.include_router(users.router)
