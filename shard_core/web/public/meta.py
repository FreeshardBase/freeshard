import io
import logging
import mimetypes

from fastapi import APIRouter, HTTPException, status
from fastapi import Cookie
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from shard_core.data_model.auth import AuthState
from shard_core.data_model.identity import OutputIdentity
from shard_core.service import pairing, identity, avatar
from shard_core.service.app_tools import get_freeshard_version

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/meta",
)


class OutputVersion(BaseModel):
    version: str


@router.get("/version", response_model=OutputVersion)
async def get_version():
    # The shard's own running version. The store (web-terminal/Sundial) reads
    # it to decide which apps are eligible: an app whose minimum_freeshard_version
    # exceeds this is hidden while not installed. The shard is the authoritative
    # source for the version it actually runs (the controller's record can lag).
    return OutputVersion(version=get_freeshard_version())


@router.get("/whoareyou", response_model=OutputIdentity)
async def who_are_you():
    return await identity.get_default_identity()


@router.get("/avatar")
async def get_default_avatar():
    default_id = await identity.get_default_identity()

    try:
        avatar_file = avatar.find_avatar_file(default_id.id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    with open(avatar_file, "rb") as icon_file:
        buffer = io.BytesIO(icon_file.read())
    return StreamingResponse(buffer, media_type=mimetypes.guess_type(avatar_file)[0])


class OutputWhoAmI(BaseModel):
    type: AuthState.ClientType
    id: str | None = None
    name: str | None = None

    @classmethod
    def anonymous(cls):
        return cls(type=AuthState.ClientType.ANONYMOUS, id=None, name=None)


@router.get("/whoami", response_model=OutputWhoAmI)
async def who_am_i(authorization: str = Cookie(None)):
    if not authorization:
        return OutputWhoAmI.anonymous()

    try:
        terminal = await pairing.verify_terminal_jwt(authorization)
    except pairing.InvalidJwt:
        return OutputWhoAmI.anonymous()
    else:
        return OutputWhoAmI(
            type=AuthState.ClientType.TERMINAL,
            id=terminal.id,
            name=terminal.name,
        )
