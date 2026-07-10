-- shard-core-0002-users
-- depends: shard-core-0001-init

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    email TEXT,
    role TEXT NOT NULL DEFAULT 'member',
    password_hash TEXT,
    disabled BOOLEAN NOT NULL DEFAULT FALSE,
    created TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE terminals ADD COLUMN IF NOT EXISTS user_id TEXT REFERENCES users (id);
