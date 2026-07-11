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
import time
from collections import deque
from urllib.parse import quote

from authlib.oauth2.rfc6749 import AuthorizationServer, OAuth2Request
from authlib.oauth2.rfc6749.requests import BasicOAuth2Payload
from fastapi import APIRouter, Cookie, Request
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

log = logging.getLogger(__name__)

router = APIRouter(prefix="/oidc", tags=["/public/oidc"])


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


async def _build_oauth2_request(request: Request) -> StarletteOAuth2Request:
    form = {}
    if request.method == "POST":
        form = {k: v for k, v in (await request.form()).items()}
    return StarletteOAuth2Request(
        method=request.method,
        url=str(request.url),
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
                issuer = f"{protocol}://{i.domain}/core/public/oidc"
                jwk = await ensure_jwk()
                configure(issuer, jwk, asyncio.get_running_loop())
                _token_request_times.clear()
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
        return ShardUser.from_user(await db_users.get_by_id(conn, terminal.user_id))


# --- token endpoint rate limit ------------------------------------------------------

_token_request_times: deque = deque()
_RATE_WINDOW = 60


def _rate_limited() -> bool:
    now = time.monotonic()
    while _token_request_times and _token_request_times[0] < now - _RATE_WINDOW:
        _token_request_times.popleft()
    if len(_token_request_times) >= TOKEN_RATE_LIMIT:
        return True
    _token_request_times.append(now)
    return False


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
        rd = quote(str(request.url), safe="")
        return RedirectResponse(f"/?oidc_rd={rd}", status_code=302)
    oreq = await _build_oauth2_request(request)
    return await asyncio.to_thread(server.create_authorization_response, oreq, user)


@router.post("/token")
async def token(request: Request):
    server = await _get_server(request)
    if _rate_limited():
        return JSONResponse({"error": "slow_down"}, status_code=429)
    oreq = await _build_oauth2_request(request)
    return await asyncio.to_thread(server.create_token_response, oreq)


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
