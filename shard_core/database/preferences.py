from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.rows import class_row

from shard_core.data_model.preferences import PreferencesRow

_WRITABLE_COLUMNS = {"language"}


async def get(conn: AsyncConnection, user_id: int) -> PreferencesRow:
    """The user's stored preferences, or an all-None row if nothing was ever written."""
    sql: LiteralString = "SELECT * FROM user_preferences WHERE user_id = %s"
    async with conn.cursor(row_factory=class_row(PreferencesRow)) as cur:
        await cur.execute(sql, (user_id,))
        row = await cur.fetchone()
    return row if row is not None else PreferencesRow(user_id=user_id)


async def put(conn: AsyncConnection, user_id: int, patch: dict) -> PreferencesRow:
    """Upsert only the given columns, leaving any other stored preference untouched.

    An empty patch is a no-op read: there is nothing to write, and an upsert with
    no SET clause would be invalid SQL.
    """
    if not patch:
        return await get(conn, user_id)
    columns = []
    for key in patch:
        if key not in _WRITABLE_COLUMNS:
            raise ValueError(f"Invalid column: {key}")
        columns.append(key)
    assignments = ", ".join(f"{c} = %({c})s" for c in columns)
    sql = f"""INSERT INTO user_preferences (user_id, {", ".join(columns)})
        VALUES (%(user_id)s, {", ".join(f"%({c})s" for c in columns)})
        ON CONFLICT (user_id) DO UPDATE SET {assignments}
        RETURNING *"""
    async with conn.cursor(row_factory=class_row(PreferencesRow)) as cur:
        await cur.execute(sql, {"user_id": user_id, **patch})
        return await cur.fetchone()
