-- shard-core-0007-user-preferences
-- depends: shard-core-0006-app-secrets

-- The owner's (and, once multi-user lands, every member's) UI preferences get
-- their own table rather than columns on `users`, so the two stay clearly
-- apart: `users` is identity, this is a per-user settings blob that grows
-- independently. One row per user, created on first write. The first
-- preference is the preferred UI language. NULL means "no preference stored
-- yet" — the client falls back to its own detection. The column is plain
-- TEXT, not a PG enum, so the set of offered languages is the UI's to grow,
-- not a shard migration.
CREATE TABLE user_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    language TEXT
);
