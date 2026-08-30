import logging

from fastapi import APIRouter, status
from pydantic import BaseModel

from shard_core.service.app_tools import docker_prune_images
from shard_core.settings import settings

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/settings",
)


class OutputSettings(BaseModel):
    """The subset of shard configuration a client is allowed to see.

    An explicit allowlist, deliberately not a projection of Settings. That
    object carries the database password, the controller base URL and the
    management API URL; a model_dump() with an exclude list would fail open,
    publishing any field added elsewhere in the config. Naming the fields here
    fails closed instead.
    """

    email_enabled: bool


@router.get("", response_model=OutputSettings)
async def get_settings():
    """What a client needs to know about how this shard is configured.

    Read-only on purpose. User-writable state lives behind
    /protected/preferences; keeping the two apart means neither payload mixes
    writable and read-only fields, so a client cannot round-trip a GET into a
    PUT and silently drop half of it.
    """
    return OutputSettings(
        # whether this shard can send mail at all: it decides both whether an
        # address must be confirmed and whether change notifications go out,
        # and a client may legitimately want to say either
        email_enabled=settings().email.enabled,
    )


@router.post("/prune-images", status_code=status.HTTP_200_OK)
async def prune_images():
    """
    Prune all unused docker images.
    """
    result = await docker_prune_images(apply_filter=False)
    return {"message": result}
