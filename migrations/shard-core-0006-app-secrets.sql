-- shard-core-0006-app-secrets
-- depends: shard-core-0005-owner-email-verification

CREATE TABLE IF NOT EXISTS app_secrets (
    app_name TEXT NOT NULL,
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (app_name, name)
);
