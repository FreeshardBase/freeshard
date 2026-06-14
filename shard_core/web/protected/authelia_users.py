import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from shard_core.service import authelia

log = logging.getLogger(__name__)

router = APIRouter(prefix="/authelia/users")


class UserOutput(BaseModel):
    username: str
    display_name: str
    email: str
    groups: List[str]


class CreateUserInput(BaseModel):
    username: str
    display_name: str
    email: str
    password: str
    groups: List[str] = []


class UpdateUserInput(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    groups: Optional[List[str]] = None


@router.get("", response_model=List[UserOutput])
def list_users():
    users = authelia.list_users()
    return [
        UserOutput(
            username=username,
            display_name=data["displayname"],
            email=data["email"],
            groups=data.get("groups") or [],
        )
        for username, data in users.items()
    ]


@router.get("/{username}", response_model=UserOutput)
def get_user(username: str):
    user = authelia.get_user(username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return UserOutput(
        username=username,
        display_name=user["displayname"],
        email=user["email"],
        groups=user.get("groups") or [],
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(body: CreateUserInput):
    try:
        authelia.create_user(
            username=body.username,
            display_name=body.display_name,
            email=body.email,
            password=body.password,
            groups=body.groups,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.patch("/{username}", status_code=status.HTTP_200_OK)
def update_user(username: str, body: UpdateUserInput):
    try:
        authelia.update_user(
            username=username,
            display_name=body.display_name,
            email=body.email,
            password=body.password,
            groups=body.groups,
        )
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.delete(
    "/{username}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
def delete_user(username: str):
    try:
        authelia.delete_user(username)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
