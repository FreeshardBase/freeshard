from fastapi import APIRouter

from . import apps

router = APIRouter(
    prefix="/management",
    tags=["/management"],
)

router.include_router(apps.router)
