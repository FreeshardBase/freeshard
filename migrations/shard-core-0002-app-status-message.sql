-- shard-core-0002-app-status-message
-- depends: shard-core-0001-init

ALTER TABLE installed_apps ADD COLUMN IF NOT EXISTS status_message TEXT;
