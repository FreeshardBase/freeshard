"""
Initial database schema for shard-core
"""

from yoyo import step

__depends__ = {}

steps = [
    step(
        """
        CREATE TABLE identities (
            id VARCHAR(128) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255),
            description TEXT,
            private_key TEXT NOT NULL,
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        DROP TABLE identities
        """,
    ),
    step(
        """
        CREATE TABLE terminals (
            id VARCHAR(128) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            icon VARCHAR(50) NOT NULL DEFAULT 'unknown',
            last_connection TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        DROP TABLE terminals
        """,
    ),
    step(
        """
        CREATE TABLE peers (
            id VARCHAR(128) PRIMARY KEY,
            name VARCHAR(255),
            public_bytes_b64 TEXT,
            is_reachable BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        DROP TABLE peers
        """,
    ),
    step(
        """
        CREATE TABLE installed_apps (
            name VARCHAR(255) PRIMARY KEY,
            status VARCHAR(50) NOT NULL,
            installation_reason VARCHAR(50) NOT NULL DEFAULT 'unknown',
            access VARCHAR(50) NOT NULL DEFAULT 'private',
            last_access TIMESTAMP,
            version VARCHAR(50),
            meta JSONB,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        DROP TABLE installed_apps
        """,
    ),
    step(
        """
        CREATE TABLE tours (
            id VARCHAR(128) PRIMARY KEY,
            completed BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        DROP TABLE tours
        """,
    ),
    step(
        """
        CREATE TABLE app_usage_track (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP NOT NULL,
            installed_apps JSONB NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        DROP TABLE app_usage_track
        """,
    ),
    step(
        """
        CREATE TABLE key_value (
            key VARCHAR(255) PRIMARY KEY,
            value JSONB NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        DROP TABLE key_value
        """,
    ),
    step(
        """
        CREATE INDEX idx_identities_is_default ON identities(is_default) WHERE is_default = TRUE
        """,
        """
        DROP INDEX idx_identities_is_default
        """,
    ),
    step(
        """
        CREATE INDEX idx_terminals_last_connection ON terminals(last_connection DESC)
        """,
        """
        DROP INDEX idx_terminals_last_connection
        """,
    ),
    step(
        """
        CREATE INDEX idx_installed_apps_status ON installed_apps(status)
        """,
        """
        DROP INDEX idx_installed_apps_status
        """,
    ),
    step(
        """
        CREATE INDEX idx_app_usage_track_timestamp ON app_usage_track(timestamp DESC)
        """,
        """
        DROP INDEX idx_app_usage_track_timestamp
        """,
    ),
]
