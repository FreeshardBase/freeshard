import logging

from fastapi import APIRouter, status, HTTPException

from portal_core.service import app_store
from portal_core.service.app_store import AppAlreadyInstalled

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/apps',
)


@router.post('/{name}', status_code=status.HTTP_201_CREATED)
def install_app(name: str):
	try:
		app_store.install_store_app(name)
	except AppAlreadyInstalled:
		raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f'App {name} is already installed')
