-- =====================================================================
-- RDS #2 (sensitive data) - least-privilege MySQL users.
--
-- Only the Lambdas that genuinely need sensitive data get a user here.
-- catalog, cart, reviews and seller have NO access to this server at all.
--
-- BEFORE RUNNING:
--   1. Run migrations/001_credentials_locked_until.sql first.
--   2. Replace every CHANGE_ME_* with a long random password
--      (use different passwords than on the core server).
--   3. Run it connected as the RDS master user.
-- =====================================================================

-- ---------- auth: password hashes + lockout counter ----------
-- DELETE is only used to undo a half-finished registration.
CREATE USER IF NOT EXISTS 'app_auth_s'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT, INSERT, DELETE ON marketplace_sensitive.credentials TO 'app_auth_s'@'%';
GRANT UPDATE (failed_attempts, locked_until, last_login) ON marketplace_sensitive.credentials TO 'app_auth_s'@'%';
GRANT UPDATE (password_hash) ON marketplace_sensitive.credentials TO 'app_auth_s'@'%';

-- ---------- account: saved cards (token + last4 only) ----------
CREATE USER IF NOT EXISTS 'app_account_s'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT, INSERT ON marketplace_sensitive.cards TO 'app_account_s'@'%';
GRANT UPDATE (is_active) ON marketplace_sensitive.cards TO 'app_account_s'@'%';

-- ---------- checkout: read card token, record payments ----------
CREATE USER IF NOT EXISTS 'app_checkout_s'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT ON marketplace_sensitive.cards TO 'app_checkout_s'@'%';
GRANT SELECT, INSERT ON marketplace_sensitive.payments TO 'app_checkout_s'@'%';
GRANT UPDATE (status, gateway_reference, paid_at) ON marketplace_sensitive.payments TO 'app_checkout_s'@'%';

-- ---------- orders: show payment status in order history ----------
CREATE USER IF NOT EXISTS 'app_orders_s'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT (id, order_id, method, amount, status, paid_at) ON marketplace_sensitive.payments TO 'app_orders_s'@'%';

FLUSH PRIVILEGES;
