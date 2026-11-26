import logging

from fastapi import APIRouter, Cookie, HTTPException, status

from shard_core.data_model.preferences import InputPreferences, OutputPreferences
from shard_core.database import preferences as db_preferences
from shard_core.database.connection import db_conn
from shard_core.web.protected._auth import session_user

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/preferences",
)


@router.get("", response_model=OutputPreferences)
async def get_preferences(authorization: str = Cookie(None)):
    """The session user's stored UI preferences.

    Always 200 for a valid session: a logged-in user always has a preferences
    object, even when every field is still empty. An unset language comes back
    as null, which the UI client treats exactly like the 404 an older shard
    (without this endpoint) returns — fall back to its own language detection.
    """
    user = await session_user(authorization)
    async with db_conn() as conn:
        prefs = await db_preferences.get(conn, user.id)
    return OutputPreferences(language=prefs.language)


@router.put("", response_model=OutputPreferences)
async def put_preferences(update: InputPreferences, authorization: str = Cookie(None)):
    """Write the given fields of the session user's UI preferences; an omitted
    field is left untouched, so a future multi-field body can update just one.
    """
    user = await session_user(authorization)
    # an omitted field is untouched, an explicit null clears it — which the
    # Optional annotation alone cannot tell apart (same idiom as users.py)
    fields = update.model_dump(exclude_unset=True)
    if "language" in fields and update.language is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="language cannot be null."
        )
    async with db_conn() as conn:
        prefs = await db_preferences.put(conn, user.id, fields)
    return OutputPreferences(language=prefs.language)
