"""Embedded OIDC provider.

Authorization server for first-party app clients: authorization-code + PKCE +
refresh, RS256 id_tokens, discovery, JWKS, userinfo. Users come from the
`users` table (phase 1); the OIDC `sub` is the stringified numeric user id.

Built on Authlib's framework-agnostic server classes; see
`shard_core.web.public.oidc` for the FastAPI adapter. Authlib's server core is
synchronous and runs in a worker thread (asyncio.to_thread); its storage hooks
bridge back to the main event loop's connection pool via
asyncio.run_coroutine_threadsafe.

Secrets at rest: client secrets, authorization codes, and access/refresh
tokens are high-entropy random strings and are stored as SHA-256 digests only.
"""

import asyncio
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import jinja2
from authlib.oauth2.rfc6749 import (
    AuthorizationServer,
    ClientMixin,
    AuthorizationCodeMixin,
    grants,
)
from authlib.oauth2.rfc7636 import CodeChallenge
from authlib.oidc.core import UserInfo
from authlib.oidc.core.grants import OpenIDCode
from joserfc.jwk import RSAKey

from shard_core.database import kv_store
from shard_core.settings import settings
from shard_core.database import oidc as db_oidc
from shard_core.database import users as db_users
from shard_core.database.connection import db_conn
from shard_core.data_model.user import User

log = logging.getLogger(__name__)

STORE_KEY_OIDC_JWK = "oidc_provider_jwk"
ACCESS_TOKEN_EXPIRES_IN = 3600
REFRESH_TOKEN_LIFETIME = 30 * 24 * 3600
CODE_EXPIRES_IN = 300
SUPPORTED_SCOPES = ["openid", "profile", "email"]
TOKEN_RATE_LIMIT = 30  # token requests per minute, enforced by the web layer

_state: dict = {"issuer": None, "jwk": None, "loop": None}


def configure(issuer: str, jwk: dict, loop: asyncio.AbstractEventLoop):
    _state["issuer"] = issuer
    _state["jwk"] = jwk
    _state["loop"] = loop


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _run(coro):
    """Bridge for Authlib's sync storage hooks (called inside asyncio.to_thread)
    back to the main event loop, where the connection pool lives."""
    return asyncio.run_coroutine_threadsafe(coro, _state["loop"]).result()


# --- models ------------------------------------------------------------------


@dataclass
class ShardUser:
    """The resource owner: a row from the users table."""

    id: int
    username: str
    display_name: str
    email: str | None = None

    @classmethod
    def from_user(cls, user: User | None):
        if user is None or user.disabled:
            return None
        return cls(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
        )

    @property
    def sub(self) -> str:
        # OIDC subject claims are strings; the numeric user id is the identity
        return str(self.id)

    def get_user_id(self):
        return self.sub


async def _user_from_id_async(user_id: int) -> ShardUser | None:
    async with db_conn() as conn:
        return ShardUser.from_user(await db_users.get_by_id(conn, user_id))


@dataclass
class OidcClient(ClientMixin):
    client_id: str
    client_secret: str | None
    app_name: str
    redirect_uris: list[str]
    scope: str
    token_endpoint_auth_method: str
    grant_types: list[str] = field(
        default_factory=lambda: ["authorization_code", "refresh_token"]
    )

    @classmethod
    def from_row(cls, row: dict | None):
        if row is None:
            return None
        return cls(
            client_id=row["client_id"],
            client_secret=row["client_secret"],
            app_name=row["app_name"],
            redirect_uris=row["redirect_uris"],
            scope=row["scope"],
            token_endpoint_auth_method=row["token_endpoint_auth_method"],
        )

    def get_client_id(self):
        return self.client_id

    def get_default_redirect_uri(self):
        return self.redirect_uris[0]

    def get_allowed_scope(self, scope):
        if not scope:
            return self.scope
        allowed = set(self.scope.split())
        return " ".join(s for s in scope.split() if s in allowed)

    def check_redirect_uri(self, redirect_uri):
        return redirect_uri in self.redirect_uris

    def check_client_secret(self, client_secret):
        return self.client_secret is not None and secrets.compare_digest(
            self.client_secret, client_secret
        )

    def check_endpoint_auth_method(self, method, endpoint):
        if endpoint == "token":
            if self.client_secret is None:
                return method == "none"
            # first-party confidential clients may use either secret method
            # (Immich sends client_secret_post; others default to basic)
            return method in ("client_secret_basic", "client_secret_post")
        return True

    def check_response_type(self, response_type):
        return response_type == "code"

    def check_grant_type(self, grant_type):
        return grant_type in self.grant_types


@dataclass
class AuthorizationCode(AuthorizationCodeMixin):
    code: str
    client_id: str
    redirect_uri: str | None
    scope: str | None
    user_sub: int
    nonce: str | None
    code_challenge: str | None
    code_challenge_method: str | None
    auth_time: int

    @classmethod
    def from_row(cls, code: str, row: dict | None):
        if row is None:
            return None
        fields = {k: row[k] for k in cls.__dataclass_fields__ if k in row}
        return cls(code=code, **fields)

    def get_redirect_uri(self):
        return self.redirect_uri

    def get_scope(self):
        return self.scope

    def get_nonce(self):
        return self.nonce

    def get_auth_time(self):
        return self.auth_time

    def get_acr(self):
        return None

    def get_amr(self):
        return None


# --- key management -------------------------------------------------------------


async def ensure_jwk() -> dict:
    """RS256 keypair for id_token signing, persisted as a private JWK in kv_store."""
    async with db_conn() as conn:
        try:
            return await kv_store.get_value(conn, STORE_KEY_OIDC_JWK)
        except KeyError:
            key = RSAKey.generate_key(2048, private=True, auto_kid=True)
            jwk = key.as_dict(private=True)
            await kv_store.set_value(conn, STORE_KEY_OIDC_JWK, jwk)
            log.info("generated OIDC provider signing key (kid=%s)", jwk.get("kid"))
            return jwk


def public_jwks() -> dict:
    public = RSAKey.import_key(_state["jwk"]).as_dict(private=False)
    public.setdefault("use", "sig")
    public.setdefault("alg", "RS256")
    return {"keys": [public]}


# --- storage bridges (called from Authlib's sync hooks) ---------------------------


async def _with_conn(fn, *args):
    async with db_conn() as conn:
        return await fn(conn, *args)


# --- grants ------------------------------------------------------------------------


class ShardAuthCodeGrant(grants.AuthorizationCodeGrant):
    TOKEN_ENDPOINT_AUTH_METHODS = ["client_secret_basic", "client_secret_post", "none"]

    def save_authorization_code(self, code, request):
        data = request.payload.data
        _run(
            _with_conn(
                db_oidc.insert_code,
                {
                    "code_hash": hash_secret(code),
                    "client_id": request.client.client_id,
                    "redirect_uri": request.payload.redirect_uri,
                    # request.scope (not payload.scope) is the scope resolved against
                    # the client's allowed scope — payload.scope would let a client
                    # escalate beyond its registered scope
                    "scope": request.scope,
                    "user_sub": request.user.id,
                    "nonce": data.get("nonce"),
                    "code_challenge": data.get("code_challenge"),
                    "code_challenge_method": data.get("code_challenge_method"),
                    "auth_time": int(time.time()),
                    "expires_at": datetime.now(timezone.utc)
                    + timedelta(seconds=CODE_EXPIRES_IN),
                },
            )
        )

    def query_authorization_code(self, code, client):
        # atomic burn-on-query: any redemption attempt (even one that later
        # fails PKCE) consumes the code, and two concurrent requests can't
        # both get it (RFC 9700 single-use)
        row = _run(_with_conn(db_oidc.redeem_code, hash_secret(code), client.client_id))
        if row is None:
            stale = _run(
                _with_conn(db_oidc.get_code, hash_secret(code), client.client_id)
            )
            if stale and stale["redeemed"]:
                # reuse of a redeemed code signals interception — kill every
                # token issued to this (client, user) grant
                _run(
                    _with_conn(
                        db_oidc.revoke_all_for_grant,
                        client.client_id,
                        stale["user_sub"],
                    )
                )
            return None
        return AuthorizationCode.from_row(code, row)

    def delete_authorization_code(self, authorization_code):
        # already consumed atomically in query_authorization_code; the row is
        # kept (redeemed) for reuse detection until it expires
        pass

    def authenticate_user(self, authorization_code):
        return _run(_user_from_id_async(authorization_code.user_sub))


class ShardRefreshTokenGrant(grants.RefreshTokenGrant):
    INCLUDE_NEW_REFRESH_TOKEN = True

    def authenticate_refresh_token(self, refresh_token):
        row = _run(
            _with_conn(db_oidc.get_token_by_refresh_hash, hash_secret(refresh_token))
        )
        if row is None:
            return None
        if row["revoked"]:
            # replay of a rotated-out refresh token — revoke the whole family
            # so a thief who rotated first doesn't keep a live token
            _run(
                _with_conn(
                    db_oidc.revoke_all_for_grant, row["client_id"], row["user_sub"]
                )
            )
            return None
        if row["issued_at"] + REFRESH_TOKEN_LIFETIME > time.time():
            return _TokenRecord(row)
        return None

    def authenticate_user(self, credential):
        return _run(_user_from_id_async(credential.row["user_sub"]))

    def revoke_old_credential(self, credential):
        _run(_with_conn(db_oidc.revoke_token, credential.row["access_token_hash"]))


class _TokenRecord:
    def __init__(self, row: dict):
        self.row = row

    def check_client(self, client):
        return self.row["client_id"] == client.client_id

    def get_scope(self):
        return self.row["scope"]

    def get_expires_in(self):
        return self.row["expires_in"]


class ShardOpenIDCode(OpenIDCode):
    def exists_nonce(self, nonce, request):
        return _run(_with_conn(db_oidc.exists_nonce, nonce, request.payload.client_id))

    def get_authorization_code_claims(self, authorization_code):
        # Base impl always emits "nonce", as null when the client sent none.
        # Strict clients (oauth4webapi/Immich) reject nonce:null vs absent.
        claims = super().get_authorization_code_claims(authorization_code)
        return {k: v for k, v in claims.items() if v is not None}

    def resolve_client_private_key(self, client):
        return _state["jwk"]

    def get_client_claims(self, client):
        return {"iss": _state["issuer"], "aud": [client.get_client_id()]}

    def generate_user_info(self, user, scope):
        info = UserInfo(sub=user.sub)
        if "profile" in scope:
            info["name"] = user.display_name
            info["preferred_username"] = user.username
        if "email" in scope and user.email:
            info["email"] = user.email
            info["email_verified"] = True
        return info


# --- server -----------------------------------------------------------------------


def _generate_bearer_token(
    grant_type,
    client,
    user=None,
    scope=None,
    expires_in=None,
    include_refresh_token=True,
):
    token = {
        "token_type": "Bearer",
        "access_token": secrets.token_urlsafe(32),
        "expires_in": expires_in or ACCESS_TOKEN_EXPIRES_IN,
        "scope": scope,
    }
    if include_refresh_token:
        token["refresh_token"] = secrets.token_urlsafe(32)
    return token


def _save_token(token: dict, request):
    _run(
        _with_conn(
            db_oidc.insert_token,
            {
                "access_token_hash": hash_secret(token["access_token"]),
                "refresh_token_hash": (
                    hash_secret(token["refresh_token"])
                    if token.get("refresh_token")
                    else None
                ),
                "client_id": request.client.client_id,
                "user_sub": request.user.id,
                "scope": token.get("scope"),
                "issued_at": int(time.time()),
                "expires_in": token["expires_in"],
            },
        )
    )


def _query_client(client_id: str):
    return OidcClient.from_row(_run(_with_conn(db_oidc.get_client, client_id)))


class S256CodeChallenge(CodeChallenge):
    # 'plain' (Authlib's default second method) sends challenge == verifier in
    # cleartext, defeating PKCE's interception protection (RFC 9700 wants S256)
    SUPPORTED_CODE_CHALLENGE_METHOD = ["S256"]


def build_authorization_server(server_cls=AuthorizationServer) -> AuthorizationServer:
    """server_cls lets the web layer pass its framework-adapter subclass."""
    server = server_cls(scopes_supported=SUPPORTED_SCOPES)
    server.query_client = _query_client
    server.save_token = _save_token
    server.register_token_generator("default", _generate_bearer_token)
    server.register_grant(
        ShardAuthCodeGrant,
        [S256CodeChallenge(required=True), ShardOpenIDCode(require_nonce=False)],
    )
    server.register_grant(ShardRefreshTokenGrant)
    return server


# --- async API for routes and app installation ---------------------------------------


async def register_client(
    app_name: str,
    redirect_uris: list[str],
    public_client: bool = False,
    scope: str = "openid profile email",
) -> dict:
    """Create the OIDC client for an installed app, or refresh its
    configuration — credentials are preserved if the app already has one.

    The client secret is stored plaintext: docker-compose templates consume it
    on every startup re-render, and it sits in the app's compose env on the
    same disk anyway. Codes and tokens, by contrast, are stored hashed.
    """
    client_secret = None if public_client else secrets.token_urlsafe(32)
    row = {
        "client_id": f"{app_name}-{secrets.token_urlsafe(6)}",
        "client_secret": client_secret,
        "app_name": app_name,
        "redirect_uris": redirect_uris,
        "scope": scope,
        "token_endpoint_auth_method": (
            "none" if public_client else "client_secret_basic"
        ),
    }
    async with db_conn() as conn:
        stored = await db_oidc.upsert_client(conn, row)
    log.info(f"registered OIDC client for app {app_name}")
    return stored


def issuer_for_domain(domain: str, disable_ssl: bool = False) -> str:
    protocol = "http" if disable_ssl else "https"
    # Traefik routes <domain>/core/* to shard_core with /core/ stripped
    return f"{protocol}://{domain}/core/public/oidc"


async def ensure_app_client(app_name: str, oidc_meta, portal) -> dict:
    """Register/refresh the app's OIDC client and return the docker-compose
    template context: client_id, client_secret, issuer."""
    redirect_uris = [
        jinja2.Template(uri).render(portal=portal) for uri in oidc_meta.redirect_uris
    ]
    client = await register_client(
        app_name,
        redirect_uris,
        public_client=oidc_meta.public_client,
        scope=oidc_meta.scope,
    )
    return {
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "issuer": issuer_for_domain(
            portal.domain, disable_ssl=settings().traefik.disable_ssl
        ),
    }


async def userinfo_for_access_token(access_token: str) -> dict | None:
    async with db_conn() as conn:
        row = await db_oidc.get_token_by_access_hash(conn, hash_secret(access_token))
        if row is None or row["issued_at"] + row["expires_in"] < time.time():
            return None
        user = ShardUser.from_user(await db_users.get_by_id(conn, row["user_sub"]))
    if user is None:
        return None
    return dict(
        ShardOpenIDCode(require_nonce=False).generate_user_info(
            user, row["scope"] or ""
        )
    )


def discovery_document() -> dict:
    issuer = _state["issuer"]
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "userinfo_endpoint": f"{issuer}/userinfo",
        "jwks_uri": f"{issuer}/jwks",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": SUPPORTED_SCOPES,
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
            "none",
        ],
        "code_challenge_methods_supported": ["S256"],
    }
