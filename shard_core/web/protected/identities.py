import io
import logging
import mimetypes
from mimetypes import guess_type
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, status
from fastapi.datastructures import UploadFile
from fastapi.responses import Response, StreamingResponse

from shard_core.database import db_methods
from shard_core.data_model.identity import Identity, OutputIdentity, InputIdentity
from shard_core.service import identity as identity_service, identity
from shard_core.service.assets import put_asset
from shard_core.service.avatar import find_avatar_file

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/identities",
)


@router.get("", response_model=List[OutputIdentity])
def list_all_identities(name: str = None):
    all_identities = db_methods.get_all_identities()
    if name:
        return [i for i in all_identities if name.lower() in i.get('name', '').lower()]
    else:
        return all_identities


@router.get("/default", response_model=OutputIdentity)
def get_default_identity():
    return identity.get_default_identity()


@router.get("/{id}", response_model=OutputIdentity)
def get_identity_by_id(id):
    identity_data = db_methods.get_identity_by_id(id)
    if identity_data:
        return identity_data
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/default/avatar")
def get_default_avatar():
    default_id = identity.get_default_identity()
    return get_avatar_by_identity(default_id.id)


@router.get("/{id}/avatar")
def get_avatar_by_identity(id):
    i = OutputIdentity.parse_obj(get_identity_by_id(id))

    try:
        avatar_file = find_avatar_file(i.id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    with open(avatar_file, "rb") as icon_file:
        buffer = io.BytesIO(icon_file.read())
    return StreamingResponse(buffer, media_type=mimetypes.guess_type(avatar_file)[0])


@router.put("", response_model=OutputIdentity, status_code=status.HTTP_201_CREATED)
def put_identity(i: InputIdentity):
    if i.id:
        existing = db_methods.get_identity_by_id(i.id)
        if existing:
            db_methods.update_identity(i.id, i.dict(exclude_unset=True))
            updated = db_methods.get_identity_by_id(i.id)
            return OutputIdentity(**updated)
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    else:
        new_identity = Identity.create(**i.dict(exclude_unset=True))
        db_methods.insert_identity(new_identity.dict())
        log.info(f"added {new_identity}")
        return new_identity


@router.put("/default/avatar")
async def put_default_avatar(file: UploadFile):
    default_id = identity.get_default_identity()
    await put_avatar(default_id.id, file)


@router.put("/{id}/avatar", status_code=status.HTTP_201_CREATED)
async def put_avatar(id: str, file: UploadFile):
    if not guess_type(file.filename)[0].startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Avatar must be an image",
        )

    try:
        existing_file = find_avatar_file(id)
    except FileNotFoundError:
        pass
    else:
        existing_file.unlink()

    i = OutputIdentity.parse_obj(get_identity_by_id(id))
    file_extension = file.filename.split(".")[-1]
    file_path = Path("avatars") / f"{i.id}.{file_extension}"
    put_asset(await file.read(), file_path, overwrite=True)


@router.delete("/default/avatar", status_code=status.HTTP_200_OK)
async def delete_default_avatar():
    default_id = identity.get_default_identity()
    await delete_avatar(default_id.id)


@router.delete("/{id}/avatar", status_code=status.HTTP_200_OK)
async def delete_avatar(id: str):
    i = OutputIdentity.parse_obj(get_identity_by_id(id))

    try:
        avatar_file = find_avatar_file(i.id)
    except FileNotFoundError:
        return

    avatar_file.unlink()


@router.post(
    "/{id}/make-default",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def make_identity_default(id):
    try:
        identity_service.make_default(id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
