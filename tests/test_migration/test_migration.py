import json
import shutil
from pathlib import Path

import pytest

from shard_core.database.connection import db_conn
from shard_core.database import (
    installed_apps as db_installed_apps,
    identities as db_identities,
    terminals as db_terminals,
    peers as db_peers,
    tours as db_tours,
    kv_store as db_kv_store,
)
from shard_core.database.tinydb_migration import migrate_tinydb_data


SAMPLE_TINYDB = Path(__file__).parent.parent / "fixtures" / "sample_tinydb.json"


@pytest.fixture
def place_tinydb_file(tmp_path):
    """Copy the sample TinyDB JSON file to the expected location."""
    dest = tmp_path / "path_root" / "core" / "shard_core_db.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(SAMPLE_TINYDB, dest)
    return dest


async def test_tinydb_migration(place_tinydb_file, db):
    """Test that TinyDB data is migrated to Postgres and the file is renamed."""
    db_file = place_tinydb_file

    # Load expected data
    with open(SAMPLE_TINYDB) as f:
        expected = json.load(f)

    # Run the migration
    await migrate_tinydb_data()

    # Verify file was renamed
    assert not db_file.exists()
    assert db_file.with_suffix(".json.backup").exists()

    # Verify data was inserted into Postgres
    async with db_conn() as conn:
        # kv_store
        kv_records = expected.get("_default", {})
        for record in kv_records.values():
            value = await db_kv_store.get_value(conn, record["key"])
            assert value is not None

        # identities
        identity_records = expected.get("identities", {})
        all_identities = await db_identities.get_all(conn)
        assert len(all_identities) == len(identity_records)
        for record in identity_records.values():
            row = await db_identities.get_by_id(conn, record["id"])
            assert row is not None
            assert row["name"] == record["name"]

        # installed_apps
        app_records = expected.get("installed_apps", {})
        all_apps = await db_installed_apps.get_all(conn)
        assert len(all_apps) == len(app_records)
        for record in app_records.values():
            row = await db_installed_apps.get_by_name(conn, record["name"])
            assert row is not None
            assert row["status"] == record["status"]

        # terminals
        terminal_records = expected.get("terminals", {})
        all_terminals = await db_terminals.get_all(conn)
        assert len(all_terminals) == len(terminal_records)

        # peers
        peer_records = expected.get("peers", {})
        all_peers = await db_peers.get_all(conn)
        assert len(all_peers) == len(peer_records)

        # backups
        backup_records = expected.get("backups", {})
        # We only have get_latest, so just check count via raw SQL
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM backups")
            count = (await cur.fetchone())[0]
        assert count == len(backup_records)

        # tours
        tour_records = expected.get("tours", {})
        all_tours = await db_tours.get_all(conn)
        assert len(all_tours) == len(tour_records)

        # app_usage_tracks
        track_records = expected.get("app_usage_track", {})
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM app_usage_tracks")
            count = (await cur.fetchone())[0]
        assert count == len(track_records)


async def test_tinydb_migration_skipped_when_no_file(db):
    """Test that migration is a no-op when no TinyDB file exists."""
    # Should not raise
    await migrate_tinydb_data()


async def test_tinydb_migration_idempotent(place_tinydb_file, db):
    """Test that running migration twice doesn't fail (file is renamed after first run)."""
    await migrate_tinydb_data()
    # Second call should be a no-op (file already renamed)
    await migrate_tinydb_data()
