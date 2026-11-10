"""FastAPI adapter for the embedded OIDC provider.

Authlib's server core is synchronous; request handling runs in a worker thread
(asyncio.to_thread) while its storage hooks bridge back to this event loop's
connection pool. The OAuth2Request is pre-built in the async route (reading
the form body is async in Starlette) and passed through.

The provider is initialized lazily on first request: the issuer is derived
from the default identity's domain (which does not exist yet at router import
time) and the signing key lives in the database.
"""

import asyncio
import logging
from urllib.parse import quote

from authlib.oauth2.rfc6749 import AuthorizationServer, OAuth2Request
from authlib.oauth2.rfc6749.requests import BasicOAuth2Payload
from authlib.oauth2.rfc6749.util import extract_basic_authorization
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from requests.structures import CaseInsensitiveDict

from shard_core.database import users as db_users
from shard_core.database.connection import db_conn
from shard_core.service import identity, pairing
from shard_core.service.oidc_provider import (
    TOKEN_RATE_LIMIT,
    ShardUser,
    build_authorization_server,
    configure,
    discovery_document,
    ensure_jwk,
    public_jwks,
    userinfo_for_access_token,
)
from shard_core.settings import settings
from shard_core.util.misc import SlidingWindow

log = logging.getLogger(__name__)

# traefik routes <domain>/core/* here and strips the prefix
CORE_PREFIX = "/core"


def _require_enabled():
    """404 rather than 403 — a shard without the rollout must not advertise an IdP."""
    if not settings().oidc.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND)


router = APIRouter(
    prefix="/oidc",
    tags=["/public/oidc"],
    dependencies=[Depends(_require_enabled)],
)


# --- request/response adapter ---------------------------------------------------


class StarletteOAuth2Request(OAuth2Request):
    def __init__(self, method: str, url: str, headers, query: dict, form: dict):
        super().__init__(method=method, uri=url, headers=headers)
        merged = {**query, **form}
        self.payload = BasicOAuth2Payload(merged)
        self._args = query
        self._form = form

    @property
    def args(self):
        return self._args

    @property
    def form(self):
        return self._form


def _public_url(request: Request) -> str:
    """The URL this request has from outside.

    Traefik terminates TLS and strips the `/core/` prefix, so the URL Starlette
    sees is neither https nor prefixed. Scheme and host come from the forwarded
    headers, the prefix from our own traefik config, and the shard's default
    identity is the fallback when the headers are absent (direct access, tests).

    Read here by hand rather than through uvicorn's proxy-header middleware:
    that middleware also rewrites request.client from X-Forwarded-For, and
    /internal/call_peer identifies the calling app by request.client.host, so
    enabling it process-wide would turn direct reach into app impersonation
    (#188). Taking the headers for the URL alone leaves request.client meaning
    the real socket peer.
    """
    proto = request.headers.get("x-forwarded-proto")
    host = request.headers.get("x-forwarded-host")
    base = (
        f"{proto}://{host}{CORE_PREFIX}"
        if proto and host
        else request.app.state.oidc_public_base
    )
    url = f"{base}{request.url.path}"
    return f"{url}?{request.url.query}" if request.url.query else url


async def _build_oauth2_request(request: Request) -> StarletteOAuth2Request:
    form = {}
    if request.method == "POST":
        form = {k: v for k, v in (await request.form()).items()}
    return StarletteOAuth2Request(
        method=request.method,
        url=_public_url(request),
        # Authlib looks headers up by canonical name ("Authorization");
        # Starlette normalizes to lowercase — bridge with a CI dict.
        headers=CaseInsensitiveDict(request.headers),
        query=dict(request.query_params),
        form=form,
    )


class StarletteAuthorizationServer(AuthorizationServer):
    def create_oauth2_request(self, request):
        if isinstance(request, OAuth2Request):
            return request
        raise RuntimeError("expected a pre-built OAuth2Request")

    def handle_response(self, status, body, headers):
        headers = dict(headers or [])
        if isinstance(body, dict):
            return JSONResponse(body, status_code=status, headers=headers)
        if 300 <= status < 400 and "Location" in headers:
            return RedirectResponse(headers["Location"], status_code=status)
        return Response(content=body or "", status_code=status, headers=headers)

    def send_signal(self, name, *args, **kwargs):
        pass


# --- lazy per-app initialization ---------------------------------------------------

_init_lock = asyncio.Lock()


async def _get_server(request: Request) -> StarletteAuthorizationServer:
    app = request.app
    if not hasattr(app.state, "oidc_server"):
        async with _init_lock:
            if not hasattr(app.state, "oidc_server"):
                i = await identity.get_default_identity()
                protocol = "http" if settings().traefik.disable_ssl else "https"
                # Traefik routes <domain>/core/* to shard_core with /core/ stripped
                app.state.oidc_public_base = f"{protocol}://{i.domain}/core"
                issuer = f"{app.state.oidc_public_base}/public/oidc"
                jwk = await ensure_jwk()
                configure(issuer, jwk, asyncio.get_running_loop())
                _token_limits.clear()
                app.state.oidc_server = build_authorization_server(
                    StarletteAuthorizationServer
                )
                log.info(f"OIDC provider initialized, issuer={issuer}")
    return app.state.oidc_server


async def _session_user(authorization: str | None) -> ShardUser | None:
    """Existing shard session (terminal JWT cookie) → the terminal's user."""
    if not authorization:
        return None
    try:
        terminal = await pairing.verify_terminal_jwt(authorization)
    except pairing.InvalidJwt:
        return None
    if terminal.user_id is None:
        return None
    async with db_conn() as conn:
        user = ShardUser.from_user(await db_users.get_by_id(conn, terminal.user_id))
    if user is not None:
        # carried into the code and token rows, so un-pairing this device
        # revokes what it authorized
        user.terminal_id = terminal.id
    return user


# --- token endpoint rate limit ------------------------------------------------------

# Per-client (not per-shard) buckets — one SlidingWindow per client_id, created
# lazily. This deliberately overrides SlidingWindow's own rationale ("a shard
# has one owner, so splitting the budget per client would only offer an
# attacker a fresh budget per source address", shard_core/util/misc.py): that
# comment is about brute-force resistance, but the problem on this endpoint is
# availability between the owner's *own* clients — a shard runs several of the
# owner's apps against this one /token endpoint, and one misbehaving or
# retry-looping app must not be able to exhaust a shared budget and 429 every
# other app's logins (#215). A confidential client's client_id is already
# authenticated at the point its secret is checked; a public client's is not,
# same caveat every public-client flow already has.
#
# Only a *failed* grant attempt charges a client's bucket — see the `token`
# route below, which checks the outcome after calling into Authlib rather than
# gating before it. A legitimate burst of logins or refresh rotations never
# trips it.
#
# In-process and single-worker, like SlidingWindow itself: resets on restart,
# and a second uvicorn worker would keep its own independent set of buckets,
# doubling the effective per-client budget. Fine while shard_core runs one
# worker; nothing here changes that pre-existing assumption.
_token_limits: dict[str, SlidingWindow] = {}


def _token_limit_for(client_id: str) -> SlidingWindow:
    if client_id not in _token_limits:
        _token_limits[client_id] = SlidingWindow(limit=TOKEN_RATE_LIMIT, window=60)
    return _token_limits[client_id]


def _client_id_from_request(oreq: OAuth2Request) -> str | None:
    """Best-effort client_id for rate-limit keying, read the same way
    Authlib's own client authenticators read it: the form for
    client_secret_post/none, the Basic auth header for client_secret_basic.
    Done by hand, before any grant validation, so the budget can be checked
    cheaply before doing the expensive work (DB round trips, secret
    comparison) that full grant processing involves.
    """
    if client_id := oreq.payload.client_id:
        return client_id
    client_id, _ = extract_basic_authorization(oreq.headers)
    return client_id


# --- endpoints -------------------------------------------------------------------


@router.get("/.well-known/openid-configuration")
async def openid_configuration(request: Request):
    await _get_server(request)
    return discovery_document()


@router.get("/jwks")
async def jwks(request: Request):
    await _get_server(request)
    return public_jwks()


@router.get("/authorize")
async def authorize(request: Request, authorization: str = Cookie(None)):
    server = await _get_server(request)
    user = await _session_user(authorization)
    if user is None:
        # No shard session: send the browser to the terminal's pairing/login UI.
        rd = quote(_public_url(request), safe="")
        return RedirectResponse(f"/?oidc_rd={rd}", status_code=302)
    oreq = await _build_oauth2_request(request)
    return await asyncio.to_thread(server.create_authorization_response, oreq, user)


@router.post("/token")
async def token(request: Request):
    server = await _get_server(request)
    oreq = await _build_oauth2_request(request)
    client_id = _client_id_from_request(oreq)

    # Reject already-exhausted clients before paying for full grant
    # processing — a peek, not a charge (see SlidingWindow.exhausted).
    if client_id is not None and _token_limit_for(client_id).exhausted():
        return Response(status_code=429)

    response = await asyncio.to_thread(server.create_token_response, oreq)

    # Charge the budget now that the outcome is known: a 4xx here is exactly
    # the failure classes this endpoint can produce (wrong client secret,
    # bad/expired/reused code, bad/expired/reused refresh token) — an
    # unauthenticated caller submitting a secret and learning from the
    # response whether it was right. A successful issuance or refresh
    # (2xx) never reaches this branch, so it never consumes the budget.
    if client_id is not None and 400 <= response.status_code < 500:
        _token_limit_for(client_id).try_acquire()

    return response


@router.get("/userinfo")
async def userinfo(request: Request):
    await _get_server(request)
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return JSONResponse(
            {"error": "invalid_token"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    info = await userinfo_for_access_token(auth[7:])
    if info is None:
        return JSONResponse(
            {"error": "invalid_token"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return info
