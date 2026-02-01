CREATE TABLE identities (
    id integer PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL,
    email TEXT,
    description TEXT,
    private_key TEXT NOT NULL,
    is_default BOOLEAN DEFAULT FALSE
);

CREATE TABLE terminals (
    id integer PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL,
    icon TEXT DEFAULT 'unknown',
    last_connection TIMESTAMP
);

CREATE TABLE peers (
    id integer PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    hash_id TEXT,
    name TEXT,
    public_bytes_b64 TEXT,
    is_reachable BOOLEAN DEFAULT TRUE
);

CREATE TABLE installed_apps (
    id integer PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL ,
    status TEXT NOT NULL,
    installation_reason TEXT,
    access TEXT DEFAULT 'private',
    last_access TIMESTAMP,
    version TEXT,
    meta JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- step: create_tours
CREATE TABLE IF NOT EXISTS tours (
    id TEXT PRIMARY KEY,
    completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- step: create_app_usage_track
CREATE TABLE IF NOT EXISTS app_usage_track (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    installed_apps JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- step: create_key_value
CREATE TABLE IF NOT EXISTS key_value (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- step: create_backup_reports
CREATE TABLE IF NOT EXISTS backup_reports (
    id SERIAL PRIMARY KEY,
    directory TEXT NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    stats JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- step: create_indexes
CREATE INDEX IF NOT EXISTS idx_identities_is_default ON identities(is_default);
CREATE INDEX IF NOT EXISTS idx_terminals_last_connection ON terminals(last_connection DESC);
CREATE INDEX IF NOT EXISTS idx_peers_created_at ON peers(created_at);
CREATE INDEX IF NOT EXISTS idx_installed_apps_status ON installed_apps(status);
CREATE INDEX IF NOT EXISTS idx_installed_apps_last_access ON installed_apps(last_access);
CREATE INDEX IF NOT EXISTS idx_app_usage_track_timestamp ON app_usage_track(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_backup_reports_end_time ON backup_reports(end_time DESC);

