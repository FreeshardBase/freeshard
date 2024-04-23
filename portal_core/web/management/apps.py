import logging

from fastapi import APIRouter, status, HTTPException

import portal_core.service.app_installation
from portal_core.service.app_installation import AppAlreadyInstalled

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/apps',
)


@router.post('/{name}', status_code=status.HTTP_201_CREATED)
async def install_app(name: str, branch: str = 'master'):
	try:
		await portal_core.service.app_installation.install_app_from_store(name, store_branch=branch)
	except AppAlreadyInstalled:
		raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f'App {name} is already installed')
