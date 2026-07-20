import secrets as pysecrets  # aliased: this module is itself named secrets
import string

from shard_core.database import app_secrets as db_app_secrets
from shard_core.database.connection import db_conn

_SECRET_ALPHABET = string.ascii_letters + string.digits
_SECRET_LENGTH = 32


def generate_secret() -> str:
    return "".join(pysecrets.choice(_SECRET_ALPHABET) for _ in range(_SECRET_LENGTH))


class SecretResolver:
    """Jinja ``secret('name')`` helper for an app's compose template.

    Returns an app-scoped secret, reusing an existing one or minting a new one
    (32 chars from ``[A-Za-z0-9]``) on first reference. New secrets are only
    remembered here; call :func:`persist_new_secrets` after rendering to store
    them. Resolving synchronously keeps rendering to a single jinja pass even
    though the DB is async.
    """

    def __init__(self, existing: dict[str, str]):
        self._existing = existing
        self.new: dict[str, str] = {}

    def __call__(self, name: str) -> str:
        if name in self._existing:
            return self._existing[name]
        if name not in self.new:
            self.new[name] = generate_secret()
        return self.new[name]


async def load_secret_resolver(app_name: str) -> SecretResolver:
    async with db_conn() as conn:
        existing = await db_app_secrets.get_all_for_app(conn, app_name)
    return SecretResolver(existing)


async def persist_new_secrets(app_name: str, resolver: SecretResolver):
    if not resolver.new:
        return
    async with db_conn() as conn:
        for name, value in resolver.new.items():
            await db_app_secrets.insert(conn, app_name, name, value)
