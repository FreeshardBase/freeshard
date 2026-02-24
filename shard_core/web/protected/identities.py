import io
import logging
import mimetypes
from mimetypes import guess_type
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, status
from fastapi.datastructures import UploadFile
from fastapi.responses import Response, StreamingResponse

from shard_core.database.connection import db_conn
from shard_core.database import identities as identities_db
from shard_core.data_model.identity import Identity, OutputIdentity, InputIdentity
from shard_core.service import identity as identity_service, identity
from shard_core.service.assets import put_asset
from shard_core.service.avatar import find_avatar_file

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/identities",
)


@router.get("", response_model=List[OutputIdentity])
async def list_all_identities(name: str = None):
    async with db_conn() as conn:
        if name:
            return await identities_db.search_by_name(conn, name)
        else:
            return await identities_db.get_all(conn)


@router.get("/default", response_model=OutputIdentity)
async def get_default_identity():
    return await identity.get_default_identity()


@router.get("/{id}", response_model=OutputIdentity)
async def get_identity_by_id(id):
    async with db_conn() as conn:
        i = await identities_db.get_by_id(conn, id)
    if i:
        return i
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/default/avatar")
async def get_default_avatar():
    default_id = await identity.get_default_identity()
    return await get_avatar_by_identity(default_id.id)


@router.get("/{id}/avatar")
async def get_avatar_by_identity(id):
    i_row = await get_identity_by_id(id)
    i = OutputIdentity.parse_obj(i_row)

    try:
        avatar_file = find_avatar_file(i.id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    with open(avatar_file, "rb") as icon_file:
        buffer = io.BytesIO(icon_file.read())
    return StreamingResponse(buffer, media_type=mimetypes.guess_type(avatar_file)[0])


@router.put("", response_model=OutputIdentity, status_code=status.HTTP_201_CREATED)
async def put_identity(i: InputIdentity):
    async with db_conn() as conn:
        if i.id:
            existing = await identities_db.get_by_id(conn, i.id)
            if existing:
                await identities_db.update(conn, i.id, i.dict(exclude_unset=True))
                updated = await identities_db.get_by_id(conn, i.id)
                return OutputIdentity(**updated)
            else:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        else:
            new_identity = Identity.create(**i.dict(exclude_unset=True))
            await identities_db.insert(conn, new_identity.dict())
            log.info(f"added {new_identity}")
            return new_identity


@router.put("/default/avatar")
async def put_default_avatar(file: UploadFile):
    default_id = await identity.get_default_identity()
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

    i_row = await get_identity_by_id(id)
    i = OutputIdentity.parse_obj(i_row)
    file_extension = file.filename.split(".")[-1]
    file_path = Path("avatars") / f"{i.id}.{file_extension}"
    put_asset(await file.read(), file_path, overwrite=True)


@router.delete("/default/avatar", status_code=status.HTTP_200_OK)
async def delete_default_avatar():
    default_id = await identity.get_default_identity()
    await delete_avatar(default_id.id)


@router.delete("/{id}/avatar", status_code=status.HTTP_200_OK)
async def delete_avatar(id: str):
    i_row = await get_identity_by_id(id)
    i = OutputIdentity.parse_obj(i_row)

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
async def make_identity_default(id):
    try:
        await identity_service.make_default(id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
