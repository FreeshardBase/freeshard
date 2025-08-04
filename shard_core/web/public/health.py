import logging

from fastapi import APIRouter
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/health",
)


class Health(BaseModel):
    status: str


@router.get("", response_model=Health)
def health():
    return Health(status="ok")
