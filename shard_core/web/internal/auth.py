import logging
from typing import Optional

import gconf
from cachetools import TTLCache
from fastapi import HTTPException, APIRouter, Cookie, Response, status, Header, Request
from http_message_signatures import InvalidSignature
from jinja2 import Template

from shard_core.database.connection import db_conn
from shard_core.database import installed_apps as installed_apps_db
from shard_core.database import identities as identities_db
from shard_core.data_model.app_meta import InstalledApp, Access, Path
from shard_core.data_model.auth import AuthState
from shard_core.data_model.identity import Identity, SafeIdentity
from shard_core.service import pairing, peer as peer_service
from shard_core.service.app_tools import get_app_metadata
from shard_core.service.freeshard_controller import (
    validate_shared_secret,
    SharedSecretInvalid,
)
from shard_core.util.signals import on_terminal_auth, on_request_to_app, on_peer_auth

log = logging.getLogger(__name__)

router = APIRouter()

_identity_cache = TTLCache(maxsize=8, ttl=gconf.get("tests.cache_ttl", default=3))
_app_cache = TTLCache(maxsize=32, ttl=gconf.get("tests.cache_ttl", default=3))


@router.get("/authenticate_terminal", status_code=status.HTTP_200_OK)
async def authenticate_terminal(response: Response, authorization: str = Cookie(None)):
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    try:
        terminal = await pairing.verify_terminal_jwt(authorization)
    except pairing.InvalidJwt:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    else:
        response.headers["X-Ptl-Client-Type"] = "terminal"
        response.headers["X-Ptl-Client-Id"] = terminal.id
        response.headers["X-Ptl-Client-Name"] = terminal.name
        on_terminal_auth.send(terminal)


@router.get("/authenticate_management", status_code=status.HTTP_200_OK)
async def authenticate_management(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    try:
        await validate_shared_secret(authorization)
    except SharedSecretInvalid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)


@router.get("/auth", status_code=status.HTTP_200_OK)
async def authenticate_and_authorize(
    request: Request,
    response: Response,
    authorization: str = Cookie(None),
    x_forwarded_host: str = Header(None),
    x_forwarded_uri: str = Header(None),
):
    app = await _match_app(x_forwarded_host)
    path_object = _match_path(x_forwarded_uri, app)
    auth_state = await _get_auth_state(request, authorization)
    log.debug(f"Auth state is {auth_state}")
    header_values = await _get_identity()

    if (
        path_object.access == Access.PRIVATE
        and auth_state.type != AuthState.ClientType.TERMINAL
    ):
        log.debug(f"denied terminal auth for {x_forwarded_host}{x_forwarded_uri}")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    if (
        path_object.access == Access.PEER
        and auth_state.type != AuthState.ClientType.PEER
    ):
        log.debug(f"denied peer auth for {x_forwarded_host}{x_forwarded_uri}")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    if path_object.headers:
        for header_key, header_template in path_object.headers.items():
            response.headers[header_key] = Template(header_template).render(
                auth=auth_state.header_values, portal=header_values
            )
    log.debug(
        f"granted auth for {x_forwarded_host}{x_forwarded_uri} with headers {response.headers.items()}"
    )

    on_request_to_app.send(app)


async def _match_app(x_forwarded_host) -> InstalledApp:
    app_name = x_forwarded_host.split(".")[0]
    app = await _find_app(app_name)
    if not app:
        log.debug(f"denied auth for {x_forwarded_host} -> unknown app")
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return app


async def _get_identity():
    cache_key = "default"
    if cache_key in _identity_cache:
        return _identity_cache[cache_key]
    async with db_conn() as conn:
        default_identity_row = await identities_db.get_default(conn)
    default_identity = Identity(**default_identity_row)
    result = SafeIdentity.from_identity(default_identity)
    _identity_cache[cache_key] = result
    return result


async def _find_app(app_name) -> Optional[InstalledApp]:
    if app_name in _app_cache:
        return _app_cache[app_name]
    async with db_conn() as conn:
        result = await installed_apps_db.get_by_name(conn, app_name)
    if result:
        app = InstalledApp(**result)
        _app_cache[app_name] = app
        return app
    return None


def _match_path(uri, app: InstalledApp) -> Path:
    app_meta = get_app_metadata(app.name)
    for path, props in sorted(
        app_meta.paths.items(), key=lambda x: len(x[0]), reverse=True
    ):  # type: (str, Path)
        if uri.startswith(path):
            return props


async def _get_auth_state(request, authorization) -> AuthState:
    try:
        terminal = await pairing.verify_terminal_jwt(authorization)
    except pairing.InvalidJwt as e:
        log.debug(f"invalid terminal JWT: {e}")
    else:
        on_terminal_auth.send(terminal)
        return AuthState(
            x_ptl_client_type=AuthState.ClientType.TERMINAL,
            x_ptl_client_id=terminal.id,
            x_ptl_client_name=terminal.name,
        )

    try:
        peer = await peer_service.verify_peer_auth(request)
    except InvalidSignature as e:
        log.debug(f"invalid signature: {e}")
    except KeyError as e:
        log.debug(f"no such peer: {e}")
    else:
        on_peer_auth.send(peer)
        return AuthState(
            x_ptl_client_type=AuthState.ClientType.PEER,
            x_ptl_client_id=peer.id,
            x_ptl_client_name=peer.name,
        )

    return AuthState(
        x_ptl_client_type=AuthState.ClientType.ANONYMOUS,
    )
