import logging

from fastapi import APIRouter, Cookie

from shard_core.data_model.preferences import InputPreferences, OutputPreferences
from shard_core.database import users as db_users
from shard_core.database.connection import db_conn
from shard_core.web.protected.session import session_user

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/preferences",
)


@router.get("", response_model=OutputPreferences)
async def get_preferences(authorization: str = Cookie(None)):
    """The session user's stored UI preferences.

    Always 200 for a valid session: a logged-in user always has a preferences
    object, even when every field is still empty. An unset language comes back
    as null, which the web-terminal treats exactly like the 404 an older shard
    (without this endpoint) returns — fall back to its own language detection.
    """
    user = await session_user(authorization)
    return OutputPreferences(language=user.language)


@router.put("", response_model=OutputPreferences)
async def put_preferences(update: InputPreferences, authorization: str = Cookie(None)):
    """Persist the session user's UI preferences, returning the stored result."""
    user = await session_user(authorization)
    async with db_conn() as conn:
        user = await db_users.update(conn, user.id, {"language": update.language})
    return OutputPreferences(language=user.language)
