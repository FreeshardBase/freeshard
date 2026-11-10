-- shard-core-0008-oidc-backchannel-logout-outbox
-- depends: shard-core-0006-app-secrets
--
-- Picked 0008 rather than the next free slot after 0006: PR #260
-- (shard-core-0007-user-preferences) was open against main at the time this
-- was written. Both migrations depend on 0006, so either merge order is fine.

-- The rendered, ready-to-POST backchannel_logout_uri for this app's OIDC
-- client. Not set at enqueue/delivery time by re-reading app_meta.json --
-- resolved once at client (re-)registration, same as redirect_uris, so
-- delivery never depends on the app's on-disk metadata still matching what
-- was true when the grant was issued.
ALTER TABLE oidc_clients ADD COLUMN backchannel_logout_uri TEXT;

-- Durable outbox: one row per (client_id, sid) that needs an OIDC
-- Back-Channel Logout 1.0 notification delivered. Durable rather than an
-- in-memory queue on purpose -- the installation worker's in-memory queue is
-- a known crash-loss hazard that needed reconcile_interrupted_installs() /
-- reconcile_interrupted_uninstalls() to compensate (see app_factory.py); an
-- outbox row surviving a restart needs no such reconciliation step, it is
-- just picked up again by the next drain.
CREATE TABLE IF NOT EXISTS oidc_backchannel_logout_outbox (
    id BIGSERIAL PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES oidc_clients (client_id) ON DELETE CASCADE,
    user_sub BIGINT NOT NULL,
    sid TEXT NOT NULL,
    -- Informational only, deliberately no FK: the un-pair that writes this
    -- row deletes the terminals row in the same transaction (terminal_id on
    -- oidc_tokens/oidc_codes is ON DELETE SET NULL), so by the time this row
    -- is ever read back the terminal it names is already gone. Kept purely
    -- as a label for a future "delivery failed for this device" UI marker
    -- (tracked separately in the Sundial repo, not built here).
    terminal_id TEXT,
    attempts INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error TEXT,
    -- 'pending' | 'delivered' | 'failed' (failed = retries exhausted).
    -- Plain TEXT rather than an enum type: written only by this one module,
    -- never synced from an external contract.
    status TEXT NOT NULL DEFAULT 'pending',
    created TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (client_id, sid)
);

CREATE INDEX IF NOT EXISTS oidc_backchannel_logout_outbox_due_idx
    ON oidc_backchannel_logout_outbox (next_attempt_at)
    WHERE status = 'pending';
