from datetime import datetime

from pydantic import BaseModel


class OidcClient(BaseModel):
    """A row of oidc_clients — the OIDC client registered for an installed app."""

    client_id: str
    client_secret: str | None = None
    app_name: str
    redirect_uris: list[str]
    scope: str
    token_endpoint_auth_method: str
    # OIDC Back-Channel Logout 1.0 endpoint, already rendered (portal
    # variables resolved) at registration time. None: the app declared no
    # backchannel_logout_uri in app_meta.json and cannot be signed out from
    # our side, only from its own UI.
    backchannel_logout_uri: str | None = None
    created: datetime | None = None


class OidcCode(BaseModel):
    """A row of oidc_codes. The code itself is only ever stored as a digest."""

    code_hash: str
    client_id: str
    redirect_uri: str | None = None
    scope: str | None = None
    user_sub: int
    terminal_id: str | None = None
    sid: str
    nonce: str | None = None
    code_challenge: str | None = None
    code_challenge_method: str | None = None
    auth_time: int
    expires_at: datetime
    redeemed: bool = False


class OidcToken(BaseModel):
    """A row of oidc_tokens. Both tokens are only ever stored as digests."""

    access_token_hash: str
    refresh_token_hash: str | None = None
    client_id: str
    user_sub: int
    terminal_id: str | None = None
    sid: str
    scope: str | None = None
    issued_at: int
    expires_in: int
    revoked: bool = False
