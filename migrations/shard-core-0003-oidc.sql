-- shard-core-0003-oidc
-- depends: shard-core-0002-users

CREATE TABLE IF NOT EXISTS oidc_clients (
    client_id TEXT PRIMARY KEY,
    client_secret TEXT,
    app_name TEXT UNIQUE NOT NULL,
    redirect_uris JSONB NOT NULL,
    scope TEXT NOT NULL DEFAULT 'openid profile email',
    token_endpoint_auth_method TEXT NOT NULL DEFAULT 'client_secret_basic',
    created TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oidc_codes (
    code_hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES oidc_clients (client_id) ON DELETE CASCADE,
    redirect_uri TEXT,
    scope TEXT,
    user_sub BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    nonce TEXT,
    code_challenge TEXT,
    code_challenge_method TEXT,
    auth_time BIGINT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS oidc_tokens (
    access_token_hash TEXT PRIMARY KEY,
    refresh_token_hash TEXT UNIQUE,
    client_id TEXT NOT NULL REFERENCES oidc_clients (client_id) ON DELETE CASCADE,
    user_sub BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    scope TEXT,
    issued_at BIGINT NOT NULL,
    expires_in BIGINT NOT NULL,
    revoked BOOLEAN NOT NULL DEFAULT FALSE
);
