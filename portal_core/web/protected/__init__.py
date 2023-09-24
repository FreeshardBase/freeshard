from fastapi import APIRouter

from . import apps, backup, feedback, identities, peers, terminals, help, management, settings, ws

router = APIRouter(
	prefix='/protected',
	tags=['/protected'],
)

router.include_router(apps.router)
router.include_router(backup.router)
router.include_router(feedback.router)
router.include_router(identities.router)
router.include_router(peers.router)
router.include_router(terminals.router)
router.include_router(help.router)
router.include_router(management.router)
router.include_router(settings.router)
router.include_router(ws.router)
