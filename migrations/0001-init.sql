CREATE TABLE identities (
    id integer PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    hash_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    email TEXT,
    description TEXT,
    private_key TEXT NOT NULL,
    is_default BOOLEAN DEFAULT FALSE
);

CREATE TABLE terminals (
    id integer PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    terminal_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    icon TEXT DEFAULT 'unknown',
    last_connection TIMESTAMP
);

CREATE TABLE peers (
    id integer PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    hash_id TEXT NOT NULL UNIQUE,
    name TEXT,
    public_bytes_b64 TEXT,
    is_reachable BOOLEAN DEFAULT TRUE
);

CREATE TABLE installed_apps (
    id integer PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    installation_reason TEXT,
    access TEXT DEFAULT 'private',
    last_access TIMESTAMP,
    version TEXT,
    meta JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tours (
    id integer PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    tour_id TEXT NOT NULL UNIQUE,
    completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE app_usage_track (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP NOT NULL,
    installed_apps JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE key_value (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE backup_reports (
    id SERIAL PRIMARY KEY,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    directories JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_identities_is_default ON identities(is_default);
CREATE INDEX idx_identities_hash_id ON identities(hash_id);
CREATE INDEX idx_terminals_last_connection ON terminals(last_connection DESC);
CREATE INDEX idx_terminals_terminal_id ON terminals(terminal_id);
CREATE INDEX idx_peers_hash_id ON peers(hash_id);
CREATE INDEX idx_installed_apps_status ON installed_apps(status);
CREATE INDEX idx_installed_apps_name ON installed_apps(name);
CREATE INDEX idx_installed_apps_last_access ON installed_apps(last_access);
CREATE INDEX idx_tours_tour_id ON tours(tour_id);
CREATE INDEX idx_app_usage_track_timestamp ON app_usage_track(timestamp DESC);
CREATE INDEX idx_backup_reports_end_time ON backup_reports(end_time DESC);


