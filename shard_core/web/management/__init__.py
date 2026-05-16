from fastapi import APIRouter

from . import apps, notify, pairing_code

router = APIRouter(
    prefix="/management",
    tags=["/management"],
)

router.include_router(apps.router)
router.include_router(notify.router)
router.include_router(pairing_code.router)
