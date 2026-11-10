-- shard-core-0008-oidc-backchannel-logout-outbox
-- depends: shard-core-0006-app-secrets

-- The rendered, ready-to-POST backchannel_logout_uri for this app's OIDC
-- client. Resolved once at client (re-)registration, same as redirect_uris
-- -- delivery never re-reads app_meta.json.
ALTER TABLE oidc_clients ADD COLUMN backchannel_logout_uri TEXT;

-- Durable outbox: one row per (client_id, sid) that needs an OIDC
-- Back-Channel Logout 1.0 notification delivered. A table rather than an
-- in-memory queue, so a row survives a restart and is simply picked up by
-- the next drain -- no separate reconciliation step needed.
CREATE TABLE IF NOT EXISTS oidc_backchannel_logout_outbox (
    id BIGSERIAL PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES oidc_clients (client_id) ON DELETE CASCADE,
    user_sub BIGINT NOT NULL,
    sid TEXT NOT NULL,
    -- Informational only, deliberately no FK: the un-pair that writes this
    -- row deletes the terminals row in the same transaction (terminal_id on
    -- oidc_tokens/oidc_codes is ON DELETE SET NULL), so by the time this row
    -- is ever read back the terminal it names is already gone.
    terminal_id TEXT,
    attempts INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT,
    -- 'pending' | 'delivered' | 'failed' (failed = retries exhausted).
    status TEXT NOT NULL DEFAULT 'pending',
    created TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (client_id, sid)
);

CREATE INDEX IF NOT EXISTS oidc_backchannel_logout_outbox_due_idx
    ON oidc_backchannel_logout_outbox (next_attempt_at)
    WHERE status = 'pending';
