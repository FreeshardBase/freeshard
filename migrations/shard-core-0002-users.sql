-- shard-core-0002-users
-- depends: shard-core-0001-init

-- Keep in sync with Role in shard_core/data_model/user.py
CREATE TYPE user_role AS ENUM ('owner', 'member');

CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    email TEXT,
    role user_role NOT NULL DEFAULT 'member',
    password_hash TEXT,
    disabled BOOLEAN NOT NULL DEFAULT FALSE,
    created TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Existing shards have their default identity at migration time; create the
-- owner user and bind existing terminals right here so user_id can be
-- NOT NULL from the start. Fresh shards have empty tables — the owner user
-- is created at startup (service.user.ensure_owner_user) before any pairing.
INSERT INTO users (username, display_name, email, role)
SELECT 'owner', COALESCE(name, 'Shard Owner'), email, 'owner'
FROM identities WHERE is_default = TRUE;

ALTER TABLE terminals ADD COLUMN user_id BIGINT REFERENCES users (id);
UPDATE terminals SET user_id = (SELECT id FROM users WHERE role = 'owner');
ALTER TABLE terminals ALTER COLUMN user_id SET NOT NULL;
