from fastapi import HTTPException, status

from shard_core.data_model.user import User
from shard_core.database import users as db_users
from shard_core.database.connection import db_conn
from shard_core.service import pairing


async def session_user(authorization: str | None) -> User:
    """The user behind the terminal session a /protected request carries.

    Traefik's forwardAuth has already established that the cookie is valid before
    the request reaches /protected; reading the JWT again here is what resolves
    *which* user is asking, which is the part forwardAuth cannot answer. Today
    every terminal binds to the owner, so this resolves to the owner; once
    members exist each resolves to themselves.

    Shared by every /protected route that needs the acting user, so the mapping
    from cookie to user — and its failure modes — lives in exactly one place.
    """
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    try:
        terminal = await pairing.verify_terminal_jwt(authorization)
    except pairing.InvalidJwt:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    async with db_conn() as conn:
        user = await db_users.get_by_id(conn, terminal.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    if user.disabled:
        # authenticated, but not allowed — re-authenticating would not help
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    return user
