-- shard-core-0001-init
-- depends:

CREATE TABLE IF NOT EXISTS installed_apps (
    name TEXT PRIMARY KEY,
    installation_reason TEXT NOT NULL DEFAULT 'unknown',
    status TEXT NOT NULL DEFAULT 'unknown',
    last_access TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS identities (
    id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT,
    description TEXT,
    private_key TEXT,
    is_default BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS terminals (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT 'unknown',
    last_connection TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS peers (
    id TEXT PRIMARY KEY,
    name TEXT,
    public_bytes_b64 TEXT,
    is_reachable BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS backups (
    id SERIAL PRIMARY KEY,
    directories JSONB,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS tours (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_usage_tracks (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    installed_apps JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS kv_store (
    key TEXT PRIMARY KEY,
    value JSONB
);
