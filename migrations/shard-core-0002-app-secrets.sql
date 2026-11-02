-- shard-core-0002-app-secrets
-- depends: shard-core-0001-init

CREATE TABLE IF NOT EXISTS app_secrets (
    app_name TEXT NOT NULL,
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (app_name, name)
);
