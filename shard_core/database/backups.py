from typing import LiteralString

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


async def insert(conn: AsyncConnection, report: dict) -> dict:
    sql: LiteralString = """INSERT INTO backups (directories, start_time, end_time)
        VALUES (%(directories)s, %(start_time)s, %(end_time)s)
        RETURNING *"""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql,
            {
                "directories": Jsonb(report["directories"]),
                "start_time": report["startTime"],
                "end_time": report["endTime"],
            },
        )
        return await cur.fetchone()


async def get_latest(conn: AsyncConnection) -> dict | None:
    sql: LiteralString = "SELECT * FROM backups ORDER BY end_time DESC LIMIT 1"
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql)
        row = await cur.fetchone()
        if row:
            return {
                "directories": row["directories"],
                "startTime": row["start_time"],
                "endTime": row["end_time"],
            }
        return None
