from fastapi import APIRouter

from . import apps, pairing_code

router = APIRouter(
    prefix="/management",
    tags=["/management"],
)

router.include_router(apps.router)
router.include_router(pairing_code.router)
