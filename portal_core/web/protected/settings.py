import logging

from fastapi import APIRouter, status

from portal_core.service.app_tools import docker_prune_images

log = logging.getLogger(__name__)

router = APIRouter(
	prefix='/settings',
)


@router.post('/prune-images', status_code=status.HTTP_204_NO_CONTENT)
async def prune_images():
	"""
	Prune all unused docker images.
	"""
	await docker_prune_images(apply_filter=False)
