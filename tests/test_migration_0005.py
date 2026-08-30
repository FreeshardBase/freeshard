"""Migration 0005 against data, which the ordinary suite never gives it.

yoyo runs every migration once per test container, against an empty database —
so 0005's DDL is smoke-tested and its three data statements always sweep zero
rows. This applies them to a scratch database seeded with the shapes real shards
are actually in.
"""

import psycopg
import pytest
from yoyo import get_backend, read_migrations

MIGRATIONS_PATH = "migrations"
BEFORE = "shard-core-0004-oidc"
UNDER_TEST = "shard-core-0005-owner-email-verification"


def _dsn(db: dict, dbname: str) -> str:
    return (
        f"host={db['host']} port={db['port']} dbname={dbname} "
        f"user={db['user']} password={db['password']}"
    )


@pytest.fixture
def scratch_db(postgres_db):
    """A database of its own, so migrations can be replayed from scratch."""
    name = "shard_core_migration_0005"
    # FORCE because yoyo keeps its connection open past apply_migrations
    drop = f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"
    with psycopg.connect(
        _dsn(postgres_db, postgres_db["dbname"]), autocommit=True
    ) as c:
        c.execute(drop)
        c.execute(f"CREATE DATABASE {name}")
    try:
        yield {**postgres_db, "dbname": name}
    finally:
        with psycopg.connect(
            _dsn(postgres_db, postgres_db["dbname"]), autocommit=True
        ) as c:
            c.execute(drop)


def _backend(db: dict):
    return get_backend(
        f"postgresql+psycopg://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['dbname']}"
    )


def _migrate(db: dict, up_to: str):
    backend = _backend(db)
    all_migrations = read_migrations(MIGRATIONS_PATH)
    selected = [m for m in all_migrations]
    keep = []
    for migration in selected:
        keep.append(migration)
        if migration.id == up_to:
            break
    with backend.lock():
        backend.apply_migrations(
            backend.to_apply(all_migrations.filter(lambda m: m in keep))
        )


def _seed_pre_0005(db: dict, identity_email, users_email):
    with psycopg.connect(_dsn(db, db["dbname"]), autocommit=True) as conn:
        conn.execute(
            """INSERT INTO identities (id, name, email, private_key, is_default)
               VALUES ('shard-id-abc', 'Shard Owner', %s, 'PEM', TRUE)""",
            (identity_email,),
        )
        conn.execute(
            """INSERT INTO users (username, display_name, email, role)
               VALUES ('owner', 'Shard Owner', %s, 'owner')""",
            (users_email,),
        )


def _owner(db: dict):
    with psycopg.connect(_dsn(db, db["dbname"])) as conn:
        return conn.execute(
            "SELECT email, pending_email FROM users WHERE role = 'owner'"
        ).fetchone()


def _identity_columns(db: dict):
    with psycopg.connect(_dsn(db, db["dbname"])) as conn:
        rows = conn.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'identities'"""
        ).fetchall()
    return {r[0] for r in rows}


def test_an_edited_address_survives_as_a_candidate(scratch_db):
    """The address the owner typed on the Public page was never verified, so it
    must arrive as something to confirm, not as the OIDC email claim."""
    _migrate(scratch_db, BEFORE)
    _seed_pre_0005(
        scratch_db,
        identity_email="max@freeshard.net",
        users_email="owner@shard-id.freeshard.cloud",
    )

    _migrate(scratch_db, UNDER_TEST)

    assert _owner(scratch_db) == (None, "max@freeshard.net")
    assert "email" not in _identity_columns(scratch_db)


def test_the_synthetic_address_is_discarded(scratch_db):
    _migrate(scratch_db, BEFORE)
    _seed_pre_0005(
        scratch_db,
        identity_email=None,
        users_email="owner@shard-id.freeshard.cloud",
    )

    _migrate(scratch_db, UNDER_TEST)

    assert _owner(scratch_db) == (None, None)


def test_an_empty_identity_address_does_not_become_a_candidate(scratch_db):
    """InputIdentity.email defaulted to "", so a Public page saved with a blank
    field stored an empty string — a candidate nobody could ever confirm."""
    _migrate(scratch_db, BEFORE)
    _seed_pre_0005(scratch_db, identity_email="", users_email=None)

    _migrate(scratch_db, UNDER_TEST)

    assert _owner(scratch_db) == (None, None)


def test_a_shard_with_no_users_row_migrates_cleanly(scratch_db):
    """A fresh shard runs the migrations before ensure_owner_user."""
    _migrate(scratch_db, BEFORE)

    _migrate(scratch_db, UNDER_TEST)

    assert _owner(scratch_db) is None
    assert "email" not in _identity_columns(scratch_db)
