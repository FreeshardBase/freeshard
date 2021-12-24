from fastapi import APIRouter

from . import auth

router = APIRouter(
	prefix='/internal',
	tags=['/internal'],
)

router.include_router(auth.router)
