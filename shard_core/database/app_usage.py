from datetime import datetime
from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


async def insert(conn: AsyncConnection, track: dict) -> dict:
    sql: LiteralString = """INSERT INTO app_usage_tracks (timestamp, installed_apps)
        VALUES (%(timestamp)s, %(installed_apps)s)
        RETURNING *"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql,
            {
                "timestamp": track["timestamp"],
                "installed_apps": Jsonb(track["installed_apps"]),
            },
        )
        return await cur.fetchone()


async def search_by_time_range(
    conn: AsyncConnection, start: datetime, end: datetime
) -> list[dict]:
    sql: LiteralString = """SELECT * FROM app_usage_tracks
        WHERE timestamp >= %(start)s AND timestamp < %(end)s"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, {"start": start, "end": end})
        return await cur.fetchall()


async def truncate(conn: AsyncConnection):
    sql: LiteralString = "DELETE FROM app_usage_tracks"
    await conn.execute(sql)
