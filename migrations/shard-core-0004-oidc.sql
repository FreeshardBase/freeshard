-- shard-core-0004-oidc
-- depends: shard-core-0003-app-status-message

CREATE TABLE IF NOT EXISTS oidc_clients (
    client_id TEXT PRIMARY KEY,
    client_secret TEXT,
    app_name TEXT UNIQUE NOT NULL,
    redirect_uris JSONB NOT NULL,
    backchannel_logout_uri TEXT,
    scope TEXT NOT NULL DEFAULT 'openid profile email',
    token_endpoint_auth_method TEXT NOT NULL DEFAULT 'client_secret_basic',
    created TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- terminal_id is ON DELETE SET NULL, deliberately not CASCADE: un-pairing must
-- leave the rows in place. A deleted token row is indistinguishable from an
-- unknown one, which loses both the ability to deny a presented token and the
-- refresh-token reuse detection that get_token_by_refresh_hash relies on.
CREATE TABLE IF NOT EXISTS oidc_codes (
    code_hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES oidc_clients (client_id) ON DELETE CASCADE,
    redirect_uri TEXT,
    scope TEXT,
    user_sub BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    terminal_id TEXT REFERENCES terminals (id) ON DELETE SET NULL,
    sid TEXT NOT NULL,
    nonce TEXT,
    code_challenge TEXT,
    code_challenge_method TEXT,
    auth_time BIGINT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    redeemed BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS oidc_codes_terminal_id_idx ON oidc_codes (terminal_id);

CREATE TABLE IF NOT EXISTS oidc_tokens (
    access_token_hash TEXT PRIMARY KEY,
    refresh_token_hash TEXT UNIQUE,
    client_id TEXT NOT NULL REFERENCES oidc_clients (client_id) ON DELETE CASCADE,
    user_sub BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    terminal_id TEXT REFERENCES terminals (id) ON DELETE SET NULL,
    sid TEXT NOT NULL,
    scope TEXT,
    issued_at BIGINT NOT NULL,
    expires_in BIGINT NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS oidc_tokens_terminal_id_idx ON oidc_tokens (terminal_id);
