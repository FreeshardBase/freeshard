from fastapi import APIRouter, Depends

from shard_core.service.traefik_secret import verify_traefik_secret

from . import apps, notify, pairing_code

router = APIRouter(
    prefix="/management",
    tags=["/management"],
    dependencies=[Depends(verify_traefik_secret)],
)

router.include_router(apps.router)
router.include_router(notify.router)
router.include_router(pairing_code.router)
