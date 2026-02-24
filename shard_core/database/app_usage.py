import logging
from datetime import datetime

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)


async def insert(conn: AsyncConnection, track: dict):
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO app_usage_tracks (timestamp, installed_apps)
               VALUES (%(timestamp)s, %(installed_apps)s)""",
            {
                "timestamp": track["timestamp"],
                "installed_apps": Jsonb(track["installed_apps"]),
            },
        )


async def search_by_time_range(
    conn: AsyncConnection, start: datetime, end: datetime
) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """SELECT * FROM app_usage_tracks
               WHERE timestamp >= %(start)s AND timestamp < %(end)s""",
            {"start": start, "end": end},
        )
        return await cur.fetchall()
