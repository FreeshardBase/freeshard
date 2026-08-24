-- shard-core-0003-app-status-message
-- depends: shard-core-0002-users

ALTER TABLE installed_apps ADD COLUMN IF NOT EXISTS status_message TEXT;
