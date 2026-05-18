"""Tests for the Authelia user management API and service layer."""

import pytest
from pathlib import Path

from shard_core.service import authelia
from shard_core.settings import settings


@pytest.fixture
def users_db_path(tmp_path, config_override):
    return Path(settings().path_root) / "core" / "authelia" / "users_database.yml"


# ── service layer tests ──────────────────────────────────────────────────────


def test_hash_password_produces_argon2id_phc_string():
    hashed = authelia.hash_password("hunter2")
    assert hashed.startswith("$argon2id$v=19$")
    parts = hashed.split("$")
    assert len(parts) == 6
    # parts: ['', 'argon2id', 'v=19', 'm=65536,t=3,p=4', salt_b64, hash_b64]
    assert parts[3] == "m=65536,t=3,p=4"


def test_hash_password_different_salts():
    h1 = authelia.hash_password("same")
    h2 = authelia.hash_password("same")
    # Random salt means different hashes even for the same password
    assert h1 != h2


def test_list_users_empty_when_no_db(users_db_path):
    assert authelia.list_users() == {}


def test_create_and_get_user(users_db_path):
    authelia.create_user(
        "alice", "Alice Smith", "alice@example.com", "secret", ["admins"]
    )
    user = authelia.get_user("alice")
    assert user is not None
    assert user["displayname"] == "Alice Smith"
    assert user["email"] == "alice@example.com"
    assert user["groups"] == ["admins"]
    assert user["password"].startswith("$argon2id$")


def test_list_users_returns_all(users_db_path):
    authelia.create_user("alice", "Alice", "alice@example.com", "pw")
    authelia.create_user("bob", "Bob", "bob@example.com", "pw")
    users = authelia.list_users()
    assert set(users.keys()) == {"alice", "bob"}


def test_create_duplicate_user_raises(users_db_path):
    authelia.create_user("alice", "Alice", "alice@example.com", "pw")
    with pytest.raises(ValueError, match="already exists"):
        authelia.create_user("alice", "Alice 2", "alice2@example.com", "pw2")


def test_update_user_display_name(users_db_path):
    authelia.create_user("alice", "Alice", "alice@example.com", "pw")
    authelia.update_user("alice", display_name="Alicia")
    user = authelia.get_user("alice")
    assert user["displayname"] == "Alicia"
    assert user["email"] == "alice@example.com"


def test_update_user_password(users_db_path):
    authelia.create_user("alice", "Alice", "alice@example.com", "old")
    old_hash = authelia.get_user("alice")["password"]
    authelia.update_user("alice", password="new")
    new_hash = authelia.get_user("alice")["password"]
    assert old_hash != new_hash
    assert new_hash.startswith("$argon2id$")


def test_update_user_groups(users_db_path):
    authelia.create_user("alice", "Alice", "alice@example.com", "pw", ["users"])
    authelia.update_user("alice", groups=["admins", "users"])
    assert authelia.get_user("alice")["groups"] == ["admins", "users"]


def test_update_nonexistent_user_raises(users_db_path):
    with pytest.raises(KeyError):
        authelia.update_user("nobody", display_name="Ghost")


def test_delete_user(users_db_path):
    authelia.create_user("alice", "Alice", "alice@example.com", "pw")
    authelia.delete_user("alice")
    assert authelia.get_user("alice") is None
    assert authelia.list_users() == {}


def test_delete_nonexistent_user_raises(users_db_path):
    with pytest.raises(KeyError):
        authelia.delete_user("nobody")


def test_users_persisted_across_reads(users_db_path):
    authelia.create_user("alice", "Alice", "alice@example.com", "pw")
    # Read again via list to simulate a fresh load from disk
    users = authelia.list_users()
    assert "alice" in users


# ── API endpoint tests ────────────────────────────────────────────────────────


async def test_api_list_users_empty(app_client):
    # Ensure the users DB exists (normally written at startup, skip here)
    authelia.get_users_db_path().parent.mkdir(parents=True, exist_ok=True)
    authelia.get_users_db_path().write_text("users: {}\n")

    resp = await app_client.get("/protected/authelia/users")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_api_create_and_get_user(app_client):
    authelia.get_users_db_path().parent.mkdir(parents=True, exist_ok=True)
    authelia.get_users_db_path().write_text("users: {}\n")

    payload = {
        "username": "bob",
        "display_name": "Bob Jones",
        "email": "bob@example.com",
        "password": "secret123",
        "groups": ["users"],
    }
    resp = await app_client.post("/protected/authelia/users", json=payload)
    assert resp.status_code == 201

    resp = await app_client.get("/protected/authelia/users/bob")
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "bob"
    assert data["display_name"] == "Bob Jones"
    assert data["email"] == "bob@example.com"
    assert data["groups"] == ["users"]


async def test_api_create_duplicate_returns_409(app_client):
    authelia.get_users_db_path().parent.mkdir(parents=True, exist_ok=True)
    authelia.get_users_db_path().write_text("users: {}\n")

    payload = {
        "username": "bob",
        "display_name": "Bob",
        "email": "b@b.com",
        "password": "pw",
    }
    await app_client.post("/protected/authelia/users", json=payload)
    resp = await app_client.post("/protected/authelia/users", json=payload)
    assert resp.status_code == 409


async def test_api_get_nonexistent_returns_404(app_client):
    authelia.get_users_db_path().parent.mkdir(parents=True, exist_ok=True)
    authelia.get_users_db_path().write_text("users: {}\n")

    resp = await app_client.get("/protected/authelia/users/nobody")
    assert resp.status_code == 404


async def test_api_update_user(app_client):
    authelia.get_users_db_path().parent.mkdir(parents=True, exist_ok=True)
    authelia.get_users_db_path().write_text("users: {}\n")

    payload = {
        "username": "carol",
        "display_name": "Carol",
        "email": "c@c.com",
        "password": "pw",
    }
    await app_client.post("/protected/authelia/users", json=payload)

    resp = await app_client.patch(
        "/protected/authelia/users/carol", json={"display_name": "Caroline"}
    )
    assert resp.status_code == 200

    data = (await app_client.get("/protected/authelia/users/carol")).json()
    assert data["display_name"] == "Caroline"


async def test_api_delete_user(app_client):
    authelia.get_users_db_path().parent.mkdir(parents=True, exist_ok=True)
    authelia.get_users_db_path().write_text("users: {}\n")

    payload = {
        "username": "dave",
        "display_name": "Dave",
        "email": "d@d.com",
        "password": "pw",
    }
    await app_client.post("/protected/authelia/users", json=payload)

    resp = await app_client.delete("/protected/authelia/users/dave")
    assert resp.status_code == 204

    resp = await app_client.get("/protected/authelia/users/dave")
    assert resp.status_code == 404
