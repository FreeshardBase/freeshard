import logging

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)


async def insert(conn: AsyncConnection, report: dict):
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO backups (directories, start_time, end_time)
               VALUES (%(directories)s, %(start_time)s, %(end_time)s)""",
            {
                "directories": Jsonb(report["directories"]),
                "start_time": report["startTime"],
                "end_time": report["endTime"],
            },
        )


async def get_latest(conn: AsyncConnection) -> dict | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM backups ORDER BY end_time DESC LIMIT 1")
        row = await cur.fetchone()
        if row:
            return {
                "directories": row["directories"],
                "startTime": row["start_time"],
                "endTime": row["end_time"],
            }
        return None
