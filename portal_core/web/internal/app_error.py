import logging

from fastapi import APIRouter, Request

log = logging.getLogger(__name__)

router = APIRouter()


@router.get('/app_error/{status}')
def app_error(status, request: Request):
	return f'Splash for error {status} and host {request.headers.get("host")}'
