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
                _token_limit.reset()
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
# other app's logins (#215).
#
# Only a *failed* grant attempt charges a bucket, and WHICH bucket depends on
# whether the caller actually proved it is the client it's failing as:
#
# - If Authlib's own client authentication succeeded (the caller knew a
#   confidential client's real secret, or named an existing public client —
#   see StampsAuthenticatedClientId.authenticate_token_endpoint_client in
#   oidc_provider.py) and the request *then* failed — bad/expired/reused
#   code, bad/expired/reused refresh token — charge that client's own
#   per-client bucket. Safe: nobody can reach this without first proving
#   they are that client.
# - If client authentication itself failed (wrong or missing secret), charge
#   the shared _token_limit below instead, same as the single counter this
#   replaced. This is NOT safe to attribute per-client: client_id is not a
#   secret (register_client stamps it as "{app_name}-{token}", visible in
#   every /authorize redirect and discoverable from the installed app list),
#   and a *wrong* secret costs an attacker nothing to supply — charging the
#   named client_id here would let any unauthenticated caller grief one
#   victim app's logins for free by simply naming it, which is the exact
#   fairness problem per-client keying exists to fix, just aimed at one
#   client instead of all of them (caught in review of this change, #215).
#   Brute-force resistance against guessing a specific client's secret stays
#   shared-fate across clients, as it already was before this change.
#
# In-process and single-worker, like SlidingWindow itself: resets on restart,
# and a second uvicorn worker would keep its own independent set of buckets,
# doubling the effective budget. Fine while shard_core runs one worker;
# nothing here changes that pre-existing assumption.
_token_limit = SlidingWindow(limit=TOKEN_RATE_LIMIT, window=60)
_token_limits: dict[str, SlidingWindow] = {}


def _token_limit_for(client_id: str) -> SlidingWindow:
    """Get-or-create. Only call this right before recording an actual charge
    (try_acquire) — the dict must not gain an entry for a client_id that was
    merely peeked at. _token_limits is only ever populated with client_ids
    Authlib has itself authenticated (see the charge logic in `token`
    below), which bounds it to the shard's real, registered clients; letting
    a peek create entries would let anyone grow it forever with arbitrary
    strings typed into the form body (caught in review, #215).
    """
    if client_id not in _token_limits:
        _token_limits[client_id] = SlidingWindow(limit=TOKEN_RATE_LIMIT, window=60)
    return _token_limits[client_id]


def _client_bucket_exhausted(client_id: str) -> bool:
    """A non-creating peek, for the pre-check only — see _token_limit_for."""
    bucket = _token_limits.get(client_id)
    return bucket is not None and bucket.exhausted()


def _client_id_from_request(oreq: OAuth2Request) -> str | None:
    """Best-effort, *unverified* client_id, read the same way Authlib's own
    client authenticators read it: the form for client_secret_post/none, the
    Basic auth header for client_secret_basic. Used only for the cheap
    pre-check below (skip expensive work for a client that's already over
    its own budget) — never to decide which bucket a failure charges, since
    nothing here confirms the caller actually is this client.
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

    # Reject an already-exhausted bucket before paying for full grant
    # processing — a peek, not a charge (see SlidingWindow.exhausted). This
    # uses the unverified client_id purely as an admission-control guess: a
    # wrong guess here only changes *when* a 429 is returned, never which
    # bucket gets charged below, so it carries none of that decision's trust
    # requirements.
    if _token_limit.exhausted() or (
        client_id is not None and _client_bucket_exhausted(client_id)
    ):
        return Response(status_code=429)

    response = await asyncio.to_thread(server.create_token_response, oreq)

    # Charge the budget now that the outcome is known. A 4xx here is exactly
    # the failure classes this endpoint can produce (wrong client secret,
    # bad/expired/reused code, bad/expired/reused refresh token) — an
    # unauthenticated caller submitting a secret and learning from the
    # response whether it was right. A successful issuance or refresh (2xx)
    # never reaches this branch, so it never consumes any budget.
    if 400 <= response.status_code < 500:
        authenticated_client_id = getattr(oreq, "authenticated_client_id", None)
        if authenticated_client_id is not None:
            # Client authentication succeeded; this request's own code or
            # refresh token then failed. Safe to charge its own bucket.
            _token_limit_for(authenticated_client_id).try_acquire()
        else:
            # Client authentication itself failed. See the big comment above
            # _token_limit for why this must not be charged to the
            # (unverified) client_id the caller merely typed into the form.
            _token_limit.try_acquire()

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
