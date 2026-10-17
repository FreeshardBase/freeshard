-- shard-core-0007-user-preferences
-- depends: shard-core-0006-app-secrets

-- The owner's (and, once multi-user lands, every member's) UI preferences live
-- on the user row so they grow with the person, not as one global blob. The
-- first one is the preferred UI language for the web-terminal. NULL means "no
-- preference stored yet" — the client falls back to its own detection. The
-- column is plain TEXT, not a PG enum, so the set of offered languages is the
-- web-terminal's to grow, not a shard migration.
ALTER TABLE users ADD COLUMN language TEXT;
