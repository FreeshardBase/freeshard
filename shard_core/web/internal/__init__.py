from fastapi import APIRouter

from . import auth, app_error, app_proxy, call_backend, call_peer

router = APIRouter(
    prefix="/internal",
    tags=["/internal"],
)

router.include_router(app_error.router)
router.include_router(app_proxy.router)
router.include_router(auth.router)
router.include_router(call_backend.router)
router.include_router(call_peer.router)
