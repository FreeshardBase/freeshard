"""Integration tests for the embedded OIDC provider.

Flows run against the real app via app_client with a paired-terminal session
cookie — the same session mechanism browsers use. Storage assertions verify
that no plaintext secret/token material lands in the database.
"""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from httpx import AsyncClient
from joserfc import jwt as joserfc_jwt
from joserfc.jwk import KeySet

from psycopg.rows import dict_row

from shard_core.database.connection import db_conn
from shard_core.database import oidc as db_oidc
from shard_core.database import terminals as db_terminals
from shard_core.database import users as db_users
from shard_core.service import oidc_provider
from shard_core.service.identity import get_default_identity
from tests.util import pair_new_terminal

AUTHORIZE = "public/oidc/authorize"
TOKEN = "public/oidc/token"
USERINFO = "public/oidc/userinfo"
JWKS = "public/oidc/jwks"
DISCOVERY = "public/oidc/.well-known/openid-configuration"

REDIRECT_URI = "http://app.testserver/oauth/callback"


def s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


async def expected_issuer() -> str:
    identity = await get_default_identity()
    return f"https://{identity.domain}/core/public/oidc"


async def make_client(public_client: bool = False, scope: str = None) -> dict:
    kwargs = {"scope": scope} if scope else {}
    return await oidc_provider.register_client(
        "testapp", [REDIRECT_URI], public_client=public_client, **kwargs
    )


async def authorize(client: AsyncClient, oidc_client: dict, verifier: str, **overrides):
    params = {
        "response_type": "code",
        "client_id": oidc_client["client_id"],
        "redirect_uri": REDIRECT_URI,
        "scope": "openid profile email",
        "state": secrets.token_urlsafe(8),
        "nonce": secrets.token_urlsafe(8),
        "code_challenge": s256(verifier),
        "code_challenge_method": "S256",
        **overrides,
    }
    params = {k: v for k, v in params.items() if v is not None}
    return params, await client.get(AUTHORIZE, params=params)


async def get_code(
    client: AsyncClient, oidc_client: dict, verifier: str, **overrides
) -> str:
    params, r = await authorize(client, oidc_client, verifier, **overrides)
    assert r.status_code == 302, r.text
    location = urlparse(r.headers["location"])
    query = parse_qs(location.query)
    registered = urlparse(params["redirect_uri"])
    assert (location.scheme, location.netloc, location.path) == (
        registered.scheme,
        registered.netloc,
        registered.path,
    )
    assert query["state"] == [params["state"]]
    return query["code"][0]


async def exchange_code(
    client: AsyncClient, oidc_client: dict, code: str, verifier: str | None, **overrides
):
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        **overrides,
    }
    if verifier is not None:
        data["code_verifier"] = verifier
    if oidc_client["client_secret"] is None:
        data.setdefault("client_id", oidc_client["client_id"])
        auth = None
    else:
        auth = (oidc_client["client_id"], oidc_client["client_secret"])
    return await client.post(TOKEN, data=data, auth=auth)


async def run_code_flow(
    client: AsyncClient, oidc_client: dict, scope: str = "openid profile email"
) -> tuple[dict, dict]:
    verifier = secrets.token_urlsafe(32)
    params, r = await authorize(client, oidc_client, verifier, scope=scope)
    assert r.status_code == 302, r.text
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    r = await exchange_code(client, oidc_client, code, verifier)
    assert r.status_code == 200, r.text
    return r.json(), params


async def jwks_keyset(client: AsyncClient) -> KeySet:
    r = await client.get(JWKS)
    assert r.status_code == 200
    return KeySet.import_key_set(r.json())


async def get_owner():
    async with db_conn() as conn:
        return await db_users.get_owner(conn)


# --- discovery + jwks ---------------------------------------------------------


async def test_discovery_document(app_client: AsyncClient):
    r = await app_client.get(DISCOVERY)
    assert r.status_code == 200
    disco = r.json()

    issuer = await expected_issuer()
    assert disco["issuer"] == issuer
    for endpoint in (
        "authorization_endpoint",
        "token_endpoint",
        "userinfo_endpoint",
        "jwks_uri",
    ):
        assert disco[endpoint].startswith(issuer + "/"), f"{endpoint} not under issuer"
    assert "code" in disco["response_types_supported"]
    assert "public" in disco["subject_types_supported"]
    assert "RS256" in disco["id_token_signing_alg_values_supported"]
    assert "openid" in disco["scopes_supported"]
    assert disco["code_challenge_methods_supported"] == ["S256"]
    assert {"authorization_code", "refresh_token"} <= set(
        disco["grant_types_supported"]
    )
    assert {"client_secret_basic", "client_secret_post", "none"} <= set(
        disco["token_endpoint_auth_methods_supported"]
    )


async def test_jwks_returns_rsa_sig_key_and_is_stable(app_client: AsyncClient):
    r = await app_client.get(JWKS)
    assert r.status_code == 200
    keys = r.json()["keys"]
    assert len(keys) == 1
    key = keys[0]
    assert key["kty"] == "RSA"
    assert key["use"] == "sig"
    assert key["alg"] == "RS256"
    assert key.get("kid")
    assert "n" in key and "e" in key
    assert "d" not in key, "private key material exposed"

    r2 = await app_client.get(JWKS)
    assert r2.json() == r.json(), "signing key must be persistent"


# --- code + PKCE flows ----------------------------------------------------------


async def test_confidential_code_pkce_flow(app_client: AsyncClient):
    await pair_new_terminal(app_client)
    oidc_client = await make_client()
    tok, params = await run_code_flow(app_client, oidc_client)

    assert tok["token_type"].lower() == "bearer"
    assert all(
        k in tok for k in ("access_token", "refresh_token", "id_token", "expires_in")
    )

    owner = await get_owner()
    keyset = await jwks_keyset(app_client)
    claims = joserfc_jwt.decode(tok["id_token"], keyset).claims
    assert claims["iss"] == await expected_issuer()
    assert claims["aud"] == [oidc_client["client_id"]]
    assert claims["nonce"] == params["nonce"]
    assert claims["sub"] == str(owner.id)
    assert claims["exp"] > claims["iat"]


async def test_id_token_omits_nonce_when_client_sent_none(app_client: AsyncClient):
    """Strict clients (oauth4webapi) reject nonce:null — the claim must be absent."""
    await pair_new_terminal(app_client)
    oidc_client = await make_client()

    verifier = secrets.token_urlsafe(32)
    params, r = await authorize(app_client, oidc_client, verifier, nonce=None)
    assert r.status_code == 302, r.text
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    r = await exchange_code(app_client, oidc_client, code, verifier)
    assert r.status_code == 200, r.text

    keyset = await jwks_keyset(app_client)
    claims = joserfc_jwt.decode(r.json()["id_token"], keyset).claims
    assert "nonce" not in claims
    assert all(v is not None for v in claims.values()), f"null claim in {claims}"


async def test_public_client_pkce_flow(app_client: AsyncClient):
    await pair_new_terminal(app_client)
    oidc_client = await make_client(public_client=True)
    assert oidc_client["client_secret"] is None

    tok, _ = await run_code_flow(app_client, oidc_client)
    assert all(k in tok for k in ("access_token", "refresh_token", "id_token"))

    # PKCE is mandatory: a token request without code_verifier must fail
    verifier = secrets.token_urlsafe(32)
    code = await get_code(app_client, oidc_client, verifier)
    r = await exchange_code(app_client, oidc_client, code, verifier=None)
    assert r.status_code == 400, r.text


async def test_client_secret_post_accepted(app_client: AsyncClient):
    """Immich authenticates with client_secret_post, not _basic."""
    await pair_new_terminal(app_client)
    oidc_client = await make_client()

    verifier = secrets.token_urlsafe(32)
    code = await get_code(app_client, oidc_client, verifier)
    r = await app_client.post(
        TOKEN,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
            "client_id": oidc_client["client_id"],
            "client_secret": oidc_client["client_secret"],
        },
    )
    assert r.status_code == 200, r.text


# --- userinfo --------------------------------------------------------------------


async def test_userinfo(app_client: AsyncClient):
    await pair_new_terminal(app_client)
    oidc_client = await make_client()
    tok, _ = await run_code_flow(app_client, oidc_client)

    owner = await get_owner()
    r = await app_client.get(
        USERINFO, headers={"Authorization": f"Bearer {tok['access_token']}"}
    )
    assert r.status_code == 200
    info = r.json()
    assert info["sub"] == str(owner.id)
    assert info["email"] == owner.email
    assert info["preferred_username"] == owner.username

    r = await app_client.get(
        USERINFO, headers={"Authorization": "Bearer garbage-token"}
    )
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"

    r = await app_client.get(USERINFO)
    assert r.status_code == 401


# --- refresh rotation --------------------------------------------------------------


async def test_refresh_rotation(app_client: AsyncClient):
    await pair_new_terminal(app_client)
    oidc_client = await make_client()
    tok, _ = await run_code_flow(app_client, oidc_client)
    auth = (oidc_client["client_id"], oidc_client["client_secret"])

    r = await app_client.post(
        TOKEN,
        data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]},
        auth=auth,
    )
    assert r.status_code == 200, r.text
    new_tok = r.json()
    assert new_tok["access_token"] != tok["access_token"]
    assert new_tok["refresh_token"] != tok["refresh_token"]

    r = await app_client.get(
        USERINFO, headers={"Authorization": f"Bearer {new_tok['access_token']}"}
    )
    assert r.status_code == 200

    # old access token is revoked
    r = await app_client.get(
        USERINFO, headers={"Authorization": f"Bearer {tok['access_token']}"}
    )
    assert r.status_code == 401

    # rotated-out refresh token is unusable
    r = await app_client.post(
        TOKEN,
        data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]},
        auth=auth,
    )
    assert r.status_code in (400, 401), r.text

    # ...and its replay is treated as compromise: the whole family dies
    r = await app_client.get(
        USERINFO, headers={"Authorization": f"Bearer {new_tok['access_token']}"}
    )
    assert r.status_code == 401, "family not revoked after refresh-token reuse"


# --- negatives -----------------------------------------------------------------------


async def test_authorize_wrong_redirect_uri_is_not_open_redirect(
    app_client: AsyncClient,
):
    await pair_new_terminal(app_client)
    oidc_client = await make_client()
    _, r = await authorize(
        app_client,
        oidc_client,
        secrets.token_urlsafe(32),
        redirect_uri="http://evil.example/steal",
    )
    assert not (
        300 <= r.status_code < 400
    ), f"must not redirect, got {r.status_code} -> {r.headers.get('location')}"
    assert r.status_code == 400, r.text


async def test_token_wrong_client_secret(app_client: AsyncClient):
    await pair_new_terminal(app_client)
    oidc_client = await make_client()
    verifier = secrets.token_urlsafe(32)
    code = await get_code(app_client, oidc_client, verifier)
    bad = {**oidc_client, "client_secret": "wrong-" + secrets.token_urlsafe(16)}
    r = await exchange_code(app_client, bad, code, verifier)
    assert r.status_code == 401, r.text


async def test_token_unknown_code(app_client: AsyncClient):
    await pair_new_terminal(app_client)
    oidc_client = await make_client()
    r = await exchange_code(
        app_client, oidc_client, "no-such-code", secrets.token_urlsafe(32)
    )
    assert r.status_code == 400, r.text


async def test_token_expired_code(app_client: AsyncClient):
    await pair_new_terminal(app_client)
    oidc_client = await make_client()
    owner = await get_owner()
    verifier = secrets.token_urlsafe(32)
    code = "expired-" + secrets.token_urlsafe(16)
    async with db_conn() as conn:
        await db_oidc.insert_code(
            conn,
            {
                "code_hash": oidc_provider.hash_secret(code),
                "client_id": oidc_client["client_id"],
                "redirect_uri": REDIRECT_URI,
                "scope": "openid",
                "user_sub": owner.id,
                "terminal_id": None,
                "sid": secrets.token_urlsafe(16),
                "nonce": None,
                "code_challenge": s256(verifier),
                "code_challenge_method": "S256",
                "auth_time": int(datetime.now(timezone.utc).timestamp()) - 600,
                "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
            },
        )
    r = await exchange_code(app_client, oidc_client, code, verifier)
    assert r.status_code == 400, r.text


async def test_code_reuse_rejected(app_client: AsyncClient):
    await pair_new_terminal(app_client)
    oidc_client = await make_client()
    verifier = secrets.token_urlsafe(32)
    code = await get_code(app_client, oidc_client, verifier)
    r = await exchange_code(app_client, oidc_client, code, verifier)
    assert r.status_code == 200, r.text
    r = await exchange_code(app_client, oidc_client, code, verifier)
    assert r.status_code == 400, r.text


async def test_anonymous_authorize_redirects_to_terminal_ui(app_client: AsyncClient):
    oidc_client = await make_client()
    params, r = await authorize(app_client, oidc_client, secrets.token_urlsafe(32))
    assert r.status_code == 302
    assert r.headers["location"].startswith("/?oidc_rd=")

    # The return leg must be the URL the browser can reach: Traefik strips
    # /core/, so an unprefixed path routes to the web-terminal, not here.
    rd = unquote(r.headers["location"].removeprefix("/?oidc_rd="))
    identity = await get_default_identity()
    assert rd.startswith(f"https://{identity.domain}/core/{AUTHORIZE}?")
    assert f"client_id={params['client_id']}" in rd


async def test_scope_narrowing(app_client: AsyncClient):
    """A client registered without "email" must not be granted it, even if requested."""
    await pair_new_terminal(app_client)
    oidc_client = await make_client(scope="openid profile")

    tok, _ = await run_code_flow(app_client, oidc_client, scope="openid profile email")
    granted = set((tok.get("scope") or "").split())
    assert "email" not in granted, f"scope escalation: granted {granted}"
    assert {"openid", "profile"} <= granted


async def test_plain_pkce_rejected(app_client: AsyncClient):
    """RFC 9700: only S256 — 'plain' sends the verifier in cleartext."""
    await pair_new_terminal(app_client)
    oidc_client = await make_client()
    verifier = secrets.token_urlsafe(32)
    params, r = await authorize(
        app_client,
        oidc_client,
        verifier,
        code_challenge=verifier,
        code_challenge_method="plain",
    )
    if 300 <= r.status_code < 400:
        query = parse_qs(urlparse(r.headers["location"]).query)
        assert "code" not in query, "code issued for plain PKCE"
        assert "error" in query
    else:
        assert r.status_code == 400, r.text


async def test_failed_redemption_burns_code(app_client: AsyncClient):
    """Any redemption attempt consumes the code — a PKCE-failing attempt
    must not leave the code redeemable."""
    await pair_new_terminal(app_client)
    oidc_client = await make_client()
    verifier = secrets.token_urlsafe(32)
    code = await get_code(app_client, oidc_client, verifier)

    r = await exchange_code(app_client, oidc_client, code, "wrong-" + verifier)
    assert r.status_code == 400, r.text

    r = await exchange_code(app_client, oidc_client, code, verifier)
    assert r.status_code == 400, "code survived a failed redemption attempt"


async def test_code_reuse_revokes_issued_tokens(app_client: AsyncClient):
    """Reuse of a redeemed code signals interception — tokens issued to the
    grant must be revoked (RFC 9700)."""
    await pair_new_terminal(app_client)
    oidc_client = await make_client()
    verifier = secrets.token_urlsafe(32)
    code = await get_code(app_client, oidc_client, verifier)

    r = await exchange_code(app_client, oidc_client, code, verifier)
    assert r.status_code == 200, r.text
    tok = r.json()

    r = await app_client.get(
        USERINFO, headers={"Authorization": f"Bearer {tok['access_token']}"}
    )
    assert r.status_code == 200

    r = await exchange_code(app_client, oidc_client, code, verifier)
    assert r.status_code == 400, r.text

    r = await app_client.get(
        USERINFO, headers={"Authorization": f"Bearer {tok['access_token']}"}
    )
    assert r.status_code == 401, "tokens not revoked after code reuse"


# --- storage hardening -----------------------------------------------------------------


async def test_no_plaintext_tokens_in_database(app_client: AsyncClient):
    await pair_new_terminal(app_client)
    oidc_client = await make_client()
    tok, _ = await run_code_flow(app_client, oidc_client)

    async with db_conn() as conn:
        token_rows = await conn.execute("SELECT * FROM oidc_tokens")
        all_values = [str(v) for row in await token_rows.fetchall() for v in row]
    for secret_value in (tok["access_token"], tok["refresh_token"]):
        assert not any(secret_value in v for v in all_values), "plaintext token stored"


async def test_token_endpoint_rate_limited(app_client: AsyncClient):
    await pair_new_terminal(app_client)
    oidc_client = await make_client()

    statuses = []
    for _ in range(oidc_provider.TOKEN_RATE_LIMIT + 5):
        r = await exchange_code(
            app_client, oidc_client, "no-such-code", secrets.token_urlsafe(32)
        )
        statuses.append(r.status_code)
    assert 429 in statuses, "token endpoint must rate-limit bursts"


@pytest.mark.config_override({"oidc": {"enabled": False}})
async def test_provider_absent_when_disabled(app_client: AsyncClient):
    await pair_new_terminal(app_client)
    for path in (DISCOVERY, JWKS, AUTHORIZE, USERINFO):
        r = await app_client.get(path)
        assert r.status_code == 404, f"{path} answered {r.status_code}"
    r = await app_client.post(TOKEN, data={"grant_type": "authorization_code"})
    assert r.status_code == 404, r.text


# --- terminal binding + revocation on un-pair -----------------------------------


async def rows(sql: str, *args) -> list[dict]:
    async with db_conn() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, args)
            return await cur.fetchall()


async def terminal_id(name: str) -> str:
    async with db_conn() as conn:
        return (await db_terminals.get_by_name(conn, name))["id"]


async def unpair(client: AsyncClient, id_: str):
    r = await client.delete(f"protected/terminals/id/{id_}")
    assert r.status_code == 204, r.text


async def test_code_and_token_are_bound_to_the_authorizing_terminal(
    app_client: AsyncClient,
):
    await pair_new_terminal(app_client, name="laptop")
    tid = await terminal_id("laptop")
    oidc_client = await make_client()

    await run_code_flow(app_client, oidc_client)

    code_rows = await rows("SELECT * FROM oidc_codes")
    assert len(code_rows) == 1
    assert code_rows[0]["terminal_id"] == tid
    assert code_rows[0]["sid"], "every authorization must get a session id"

    token_rows = await rows("SELECT * FROM oidc_tokens")
    assert len(token_rows) == 1
    assert token_rows[0]["terminal_id"] == tid
    assert token_rows[0]["sid"] == code_rows[0]["sid"]


async def test_sid_is_opaque_and_not_the_terminal_id(app_client: AsyncClient):
    await pair_new_terminal(app_client, name="laptop")
    tid = await terminal_id("laptop")
    await run_code_flow(app_client, await make_client())

    sid = (await rows("SELECT * FROM oidc_codes"))[0]["sid"]
    assert sid != tid, "sid must not leak the shard-internal terminal id to apps"


async def test_id_token_carries_sid(app_client: AsyncClient):
    await pair_new_terminal(app_client)
    tok, _ = await run_code_flow(app_client, await make_client())

    keyset = await jwks_keyset(app_client)
    claims = joserfc_jwt.decode(tok["id_token"], keyset).claims
    assert claims["sid"] == (await rows("SELECT * FROM oidc_codes"))[0]["sid"]


async def test_refresh_preserves_the_terminal_binding(app_client: AsyncClient):
    await pair_new_terminal(app_client, name="laptop")
    tid = await terminal_id("laptop")
    oidc_client = await make_client()
    tok, _ = await run_code_flow(app_client, oidc_client)
    sid = (await rows("SELECT * FROM oidc_codes"))[0]["sid"]

    r = await app_client.post(
        TOKEN,
        data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]},
        auth=(oidc_client["client_id"], oidc_client["client_secret"]),
    )
    assert r.status_code == 200, r.text

    fresh = await rows(
        "SELECT * FROM oidc_tokens WHERE access_token_hash = %s",
        oidc_provider.hash_secret(r.json()["access_token"]),
    )
    assert fresh[0]["terminal_id"] == tid, "rotation must not drop the device binding"
    assert fresh[0]["sid"] == sid


async def test_unpair_revokes_only_that_terminals_tokens(app_client: AsyncClient):
    oidc_client = await make_client()

    await pair_new_terminal(app_client, name="laptop")
    laptop_tok, _ = await run_code_flow(app_client, oidc_client)
    laptop = await terminal_id("laptop")

    await pair_new_terminal(app_client, name="desktop")
    desktop_tok, _ = await run_code_flow(app_client, oidc_client)
    desktop = await terminal_id("desktop")

    await unpair(app_client, laptop)

    revoked = await rows("SELECT * FROM oidc_tokens WHERE sid IS NOT NULL")
    by_token = {r["access_token_hash"]: r["revoked"] for r in revoked}
    assert by_token[oidc_provider.hash_secret(laptop_tok["access_token"])] is True
    assert by_token[oidc_provider.hash_secret(desktop_tok["access_token"])] is False

    r = await app_client.get(
        USERINFO, headers={"Authorization": f"Bearer {laptop_tok['access_token']}"}
    )
    assert r.status_code == 401, "un-paired device's access token must stop working"

    r = await app_client.get(
        USERINFO, headers={"Authorization": f"Bearer {desktop_tok['access_token']}"}
    )
    assert r.status_code == 200, "other devices must stay signed in"
    assert desktop != laptop


async def test_unpair_burns_codes_not_yet_redeemed(app_client: AsyncClient):
    oidc_client = await make_client()
    await pair_new_terminal(app_client, name="laptop")
    verifier = secrets.token_urlsafe(32)
    code = await get_code(app_client, oidc_client, verifier)
    laptop = await terminal_id("laptop")

    await pair_new_terminal(app_client, name="desktop")
    await unpair(app_client, laptop)

    r = await exchange_code(app_client, oidc_client, code, verifier)
    assert r.status_code == 400, "a code issued to an un-paired device must not redeem"


async def test_unpair_leaves_a_terminal_without_grants_alone(app_client: AsyncClient):
    await pair_new_terminal(app_client, name="laptop")
    laptop = await terminal_id("laptop")
    await pair_new_terminal(app_client, name="desktop")

    await unpair(app_client, laptop)
    assert await rows("SELECT * FROM oidc_tokens") == []
