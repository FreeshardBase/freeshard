import base64
import logging
import os
import secrets
import threading
from pathlib import Path
from typing import Optional

import jinja2
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from shard_core.database import database
from shard_core.data_model.identity import SafeIdentity
from shard_core.settings import settings

log = logging.getLogger(__name__)

STORE_KEY_JWT_SECRET = "authelia_jwt_secret"
STORE_KEY_SESSION_SECRET = "authelia_session_secret"
STORE_KEY_STORAGE_ENCRYPTION_KEY = "authelia_storage_encryption_key"
STORE_KEY_OIDC_HMAC_SECRET = "authelia_oidc_hmac_secret"
STORE_KEY_OIDC_PRIVATE_KEY = "authelia_oidc_private_key"

_write_lock = threading.Lock()


async def ensure_authelia_secrets() -> None:
    for key in [
        STORE_KEY_JWT_SECRET,
        STORE_KEY_SESSION_SECRET,
        STORE_KEY_STORAGE_ENCRYPTION_KEY,
        STORE_KEY_OIDC_HMAC_SECRET,
    ]:
        try:
            await database.get_value(key)
        except KeyError:
            await database.set_value(key, secrets.token_urlsafe(64))
            log.info(f"Generated Authelia secret: {key}")

    try:
        await database.get_value(STORE_KEY_OIDC_PRIVATE_KEY)
    except KeyError:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        await database.set_value(STORE_KEY_OIDC_PRIVATE_KEY, pem.decode())
        log.info("Generated Authelia OIDC private key")


async def render_authelia_config(portal: SafeIdentity) -> None:
    jwt_secret = await database.get_value(STORE_KEY_JWT_SECRET)
    session_secret = await database.get_value(STORE_KEY_SESSION_SECRET)
    storage_encryption_key = await database.get_value(STORE_KEY_STORAGE_ENCRYPTION_KEY)
    oidc_hmac_secret = await database.get_value(STORE_KEY_OIDC_HMAC_SECRET)
    oidc_private_key = await database.get_value(STORE_KEY_OIDC_PRIVATE_KEY)

    template_dir = Path.cwd() / "data" / "authelia"
    config_dir = _get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    template = jinja2.Template((template_dir / "configuration.yml.j2").read_text())
    protocol = "http" if settings().traefik.disable_ssl else "https"
    config_content = template.render(
        domain=portal.domain,
        protocol=protocol,
        jwt_secret=jwt_secret,
        session_secret=session_secret,
        storage_encryption_key=storage_encryption_key,
        oidc_hmac_secret=oidc_hmac_secret,
    )
    (config_dir / "configuration.yml").write_text(config_content)

    (config_dir / "oidc.pem").write_text(oidc_private_key)

    users_db_path = config_dir / "users_database.yml"
    if not users_db_path.exists():
        template = jinja2.Template((template_dir / "users_database.yml.j2").read_text())
        users_db_path.write_text(template.render())
        log.info("Created Authelia users_database.yml")

    log.info("Rendered Authelia configuration")


def _get_config_dir() -> Path:
    return Path(settings().path_root) / "core" / "authelia"


def get_users_db_path() -> Path:
    return _get_config_dir() / "users_database.yml"


def list_users() -> dict[str, dict]:
    path = get_users_db_path()
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("users") or {}


def get_user(username: str) -> Optional[dict]:
    return list_users().get(username)


def create_user(
    username: str,
    display_name: str,
    email: str,
    password: str,
    groups: list[str] | None = None,
) -> None:
    with _write_lock:
        path = get_users_db_path()
        data = _read_users_db(path)
        if username in data["users"]:
            raise ValueError(f"User '{username}' already exists")
        data["users"][username] = {
            "displayname": display_name,
            "email": email,
            "password": hash_password(password),
            "groups": groups or [],
        }
        _write_users_db(data, path)


def update_user(
    username: str,
    *,
    display_name: str | None = None,
    email: str | None = None,
    password: str | None = None,
    groups: list[str] | None = None,
) -> None:
    with _write_lock:
        path = get_users_db_path()
        data = _read_users_db(path)
        if username not in data["users"]:
            raise KeyError(username)
        user = data["users"][username]
        if display_name is not None:
            user["displayname"] = display_name
        if email is not None:
            user["email"] = email
        if password is not None:
            user["password"] = hash_password(password)
        if groups is not None:
            user["groups"] = groups
        _write_users_db(data, path)


def delete_user(username: str) -> None:
    with _write_lock:
        path = get_users_db_path()
        data = _read_users_db(path)
        if username not in data["users"]:
            raise KeyError(username)
        del data["users"][username]
        _write_users_db(data, path)


def hash_password(plain: str) -> str:
    salt = os.urandom(16)
    kdf = Argon2id(salt=salt, length=32, iterations=3, lanes=4, memory_cost=65536)
    digest = kdf.derive(plain.encode())
    salt_b64 = base64.b64encode(salt).decode().rstrip("=")
    hash_b64 = base64.b64encode(digest).decode().rstrip("=")
    return f"$argon2id$v=19$m=65536,t=3,p=4${salt_b64}${hash_b64}"


def _read_users_db(path: Path) -> dict:
    if not path.exists():
        return {"users": {}}
    data = yaml.safe_load(path.read_text()) or {}
    if "users" not in data or data["users"] is None:
        data["users"] = {}
    return data


def _write_users_db(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
    os.replace(tmp, path)
