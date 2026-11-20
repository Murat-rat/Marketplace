-- RDS #2 (sensitive). Run as the master user BEFORE db_users_secure.sql,
-- because that script grants UPDATE on this new column.
-- Adds a temporary lockout: after too many failed logins the account is
-- locked until this moment (UTC), then unlocks by itself.

ALTER TABLE marketplace_sensitive.credentials
  ADD COLUMN locked_until DATETIME NULL DEFAULT NULL AFTER failed_attempts;
