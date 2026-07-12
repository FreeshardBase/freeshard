"""JSON snapshot of the Postgres database for backup and restore.

Since the 0.38.0 TinyDB->Postgres migration all core state (identities incl. the
shard's private key, terminals, installed apps, kv_store incl. the backup
passphrase) lives in Postgres. The rclone backup only syncs the on-disk
directories ``core/`` and ``user_data/``; the Postgres data directory is a
sibling that is never uploaded, so a restore produces a shard with a brand-new
identity and no terminals (see issue #122).

To close that gap we dump every application table to ``core/db_snapshot.json``
right before each backup, so the snapshot rides along inside the existing
encrypted backup. On the first startup of a fresh shard that snapshot is
restored before the default identity is generated, bringing back the shard's
identity (same shard id/domain), paired terminals, and installed-app state.

This mirrors ``tinydb_migration.py`` (which restores pre-0.38 backups) but for
the Postgres era: a plain JSON snapshot avoids depending on ``pg_dump``/``psql``
binaries in the image and is restored with the same INSERT ... ON CONFLICT DO
NOTHING approach.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from shard_core.database.connection import db_conn
from shard_core.database.kv_store import _DateTimeEncoder
from shard_core.settings import settings

log = logging.getLogger(__name__)

SNAPSHOT_FILE = "core/db_snapshot.json"

# yoyo's bookkeeping tables are recreated by the migrations that run on the fresh
# shard, so they must not be part of the snapshot.
_YOYO_TABLE_MARKER = "yoyo"


def _snapshot_path() -> Path:
    return Path(settings().path_root) / SNAPSHOT_FILE


async def write_db_snapshot():
    """Dump all application tables to the snapshot file inside ``core/``.

    Written atomically (temp file + rename) so an interrupted write never leaves
    a corrupt snapshot that a later restore would read.
    """
    async with db_conn() as conn:
        tables = await _list_data_tables(conn)
        snapshot = {}
        for table in tables:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    sql.SQL("SELECT * FROM {}").format(sql.Identifier(table))
                )
                snapshot[table] = await cur.fetchall()

    path = _snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(snapshot, cls=_DateTimeEncoder))
    tmp_path.replace(path)
    total = sum(len(rows) for rows in snapshot.values())
    log.info(
        f"wrote DB snapshot ({total} rows across {len(snapshot)} tables) to {path}"
    )


async def restore_db_snapshot():
    """Restore the snapshot on a fresh shard.

    No-op when the snapshot file is absent or when the database is already
    populated (a normal restart, or a pre-0.38 backup handled by
    ``tinydb_migration``). Must run before the default identity is generated so
    the restored identity survives.
    """
    path = _snapshot_path()
    if not path.exists():
        return

    async with db_conn() as conn:
        if await _db_already_populated(conn):
            log.info("database already populated, skipping DB snapshot restore")
            return

        snapshot = json.loads(path.read_text())
        log.info(f"found DB snapshot at {path}, restoring")
        restored = 0
        for table, rows in snapshot.items():
            if not rows:
                continue
            col_types = await _column_types(conn, table)
            for row in rows:
                await _insert_row(conn, table, row, col_types)
            await _reset_sequences(conn, table, list(col_types))
            restored += len(rows)
    log.info(f"restored {restored} rows from DB snapshot")


async def _list_data_tables(conn: AsyncConnection) -> list[str]:
    async with conn.cursor() as cur:
        await cur.execute(
            """SELECT table_name FROM information_schema.tables
               WHERE table_schema = 'public'
                 AND table_type = 'BASE TABLE'
                 AND table_name NOT LIKE %s
               ORDER BY table_name""",
            (f"%{_YOYO_TABLE_MARKER}%",),
        )
        return [r[0] for r in await cur.fetchall()]


async def _db_already_populated(conn: AsyncConnection) -> bool:
    async with conn.cursor() as cur:
        await cur.execute("SELECT 1 FROM identities LIMIT 1")
        return await cur.fetchone() is not None


async def _column_types(conn: AsyncConnection, table: str) -> dict[str, str]:
    async with conn.cursor() as cur:
        await cur.execute(
            """SELECT column_name, data_type FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = %s""",
            (table,),
        )
        return {name: dtype for name, dtype in await cur.fetchall()}


async def _insert_row(
    conn: AsyncConnection, table: str, row: dict, col_types: dict[str, str]
):
    values = {c: _adapt_value(v, col_types.get(c)) for c, v in row.items()}
    columns = list(values)
    query = sql.SQL(
        "INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
        "ON CONFLICT DO NOTHING"
    ).format(
        table=sql.Identifier(table),
        columns=sql.SQL(", ").join(map(sql.Identifier, columns)),
        placeholders=sql.SQL(", ").join(map(sql.Placeholder, columns)),
    )
    await conn.execute(query, values)


def _adapt_value(value, data_type: str | None):
    if value is None:
        return None
    if data_type == "jsonb":
        return _jsonb(value)
    if data_type in ("timestamp with time zone", "timestamp without time zone"):
        return datetime.fromisoformat(value)
    return value


def _jsonb(value):
    from psycopg.types.json import Jsonb

    return Jsonb(value, dumps=lambda v: json.dumps(v, cls=_DateTimeEncoder))


async def _reset_sequences(conn: AsyncConnection, table: str, columns: list[str]):
    """Advance SERIAL sequences past the restored rows so new inserts don't collide."""
    for column in columns:
        async with conn.cursor() as cur:
            await cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (table, column))
            seq = (await cur.fetchone())[0]
            if not seq:
                continue
            await cur.execute(
                sql.SQL(
                    "SELECT setval(%s, (SELECT COALESCE(MAX({col}), 1) FROM {table}))"
                ).format(col=sql.Identifier(column), table=sql.Identifier(table)),
                (seq,),
            )
