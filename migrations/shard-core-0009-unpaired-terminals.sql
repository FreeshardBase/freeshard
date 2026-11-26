-- shard-core-0009-unpaired-terminals
-- depends: shard-core-0008-oidc-backchannel-logout-outbox

-- Unpaired devices are kept in `terminals`, flagged, until every queued
-- back-channel logout for them has been delivered. unpaired_at non-null marks
-- the device as unpaired; paired_at records when it was paired (NULL for
-- devices that existed before this migration — the UI shows "?").
ALTER TABLE terminals ADD COLUMN paired_at TIMESTAMPTZ;
ALTER TABLE terminals ADD COLUMN unpaired_at TIMESTAMPTZ;

-- Rebuild the outbox to reference the app by name rather than by a client_id
-- FK. A queued logout must survive app uninstall (which deletes the
-- oidc_clients row, so the old client_id FK would cascade the row away) and be
-- delivered against whatever client the app has after it is installed again.
-- #302 is unreleased, so no shard has queued logouts: dropping and recreating
-- the table loses nothing.
DROP TABLE oidc_backchannel_logout_outbox;

CREATE TABLE oidc_backchannel_logout_outbox (
    id BIGSERIAL PRIMARY KEY,
    app_name TEXT NOT NULL,
    user_sub BIGINT NOT NULL,
    sid TEXT NOT NULL,
    -- ON DELETE CASCADE: deleting the device (all delivered, or dismissed)
    -- removes its rows, so delivered rows never accumulate.
    terminal_id TEXT NOT NULL REFERENCES terminals (id) ON DELETE CASCADE,
    attempts INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT,
    -- 'pending' | 'in_flight' | 'delivered' | 'failed' (failed = retries exhausted).
    status TEXT NOT NULL DEFAULT 'pending',
    created TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (app_name, sid)
);

CREATE INDEX IF NOT EXISTS oidc_backchannel_logout_outbox_due_idx
    ON oidc_backchannel_logout_outbox (next_attempt_at)
    WHERE status = 'pending';
