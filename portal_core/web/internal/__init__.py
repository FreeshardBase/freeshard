from fastapi import APIRouter

from . import auth, app_error, call_backend, call_peer

router = APIRouter(
	prefix='/internal',
	tags=['/internal'],
)

router.include_router(app_error.router)
router.include_router(auth.router)
router.include_router(call_backend.router)
router.include_router(call_peer.router)
