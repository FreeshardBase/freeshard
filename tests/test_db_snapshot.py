from datetime import datetime, timezone

import pytest
from psycopg.types.json import Jsonb

from shard_core.database.connection import db_conn
from shard_core.database.db_snapshot import (
    write_db_snapshot,
    restore_db_snapshot,
    _snapshot_path,
)
from tests.conftest import settings_override

_APP_TABLES = (
    "identities, terminals, installed_apps, peers, backups, tours, "
    "app_usage_tracks, kv_store"
)


async def _truncate_app_tables():
    async with db_conn() as conn:
        await conn.execute(f"TRUNCATE {_APP_TABLES} RESTART IDENTITY CASCADE")


async def _seed_shard_state():
    now = datetime.now(timezone.utc)
    async with db_conn() as conn:
        await conn.execute("""INSERT INTO identities (id, name, private_key, is_default)
               VALUES ('shard-id-abc', 'default', 'PRIVATE-KEY-PEM', TRUE)""")
        await conn.execute(
            "INSERT INTO terminals (id, name, icon) VALUES ('term-1', 'laptop', 'x')"
        )
        await conn.execute(
            """INSERT INTO installed_apps (name, installation_reason, status)
               VALUES ('filebrowser', 'user', 'STOPPED')"""
        )
        await conn.execute(
            "INSERT INTO kv_store (key, value) VALUES ('backup_passphrase', %s)",
            (Jsonb("correct horse battery staple"),),
        )
        await conn.execute(
            "INSERT INTO backups (directories, start_time, end_time) VALUES (%s, %s, %s)",
            (Jsonb([]), now, now),
        )


@pytest.mark.asyncio
async def test_snapshot_roundtrip_restores_core_state(db, tmp_path):
    with settings_override({"path_root": str(tmp_path)}):
        await _seed_shard_state()
        await write_db_snapshot()
        assert _snapshot_path().exists()

        # Simulate a fresh shard: empty DB, then restore from the snapshot.
        await _truncate_app_tables()
        await restore_db_snapshot()

        async with db_conn() as conn:
            identity = await (
                await conn.execute("SELECT id, private_key, is_default FROM identities")
            ).fetchone()
            assert identity == ("shard-id-abc", "PRIVATE-KEY-PEM", True)

            terminal = await (await conn.execute("SELECT id FROM terminals")).fetchone()
            assert terminal == ("term-1",)

            app = await (
                await conn.execute("SELECT name, status FROM installed_apps")
            ).fetchone()
            assert app == ("filebrowser", "STOPPED")

            passphrase = await (
                await conn.execute(
                    "SELECT value FROM kv_store WHERE key = 'backup_passphrase'"
                )
            ).fetchone()
            assert passphrase[0] == "correct horse battery staple"

            # SERIAL sequence advanced past the restored row → new insert must not collide.
            new_id = await (
                await conn.execute(
                    "INSERT INTO backups (directories) VALUES (%s) RETURNING id",
                    (Jsonb([]),),
                )
            ).fetchone()
            assert new_id[0] == 2


@pytest.mark.asyncio
async def test_restore_skipped_when_db_already_populated(db, tmp_path):
    with settings_override({"path_root": str(tmp_path)}):
        await _seed_shard_state()
        await write_db_snapshot()

        # A normal restart: the DB already holds a different identity.
        await _truncate_app_tables()
        async with db_conn() as conn:
            await conn.execute("""INSERT INTO identities (id, name, is_default)
                   VALUES ('other-id', 'default', TRUE)""")

        await restore_db_snapshot()

        async with db_conn() as conn:
            ids = [
                r[0]
                for r in await (
                    await conn.execute("SELECT id FROM identities")
                ).fetchall()
            ]
        assert ids == ["other-id"]


@pytest.mark.asyncio
async def test_restore_noop_without_snapshot_file(db, tmp_path):
    with settings_override({"path_root": str(tmp_path)}):
        assert not _snapshot_path().exists()
        await restore_db_snapshot()  # must not raise
