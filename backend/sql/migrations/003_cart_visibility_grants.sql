-- =====================================================================
-- Migration 003 - cart Lambda (RDS #1, marketplace_core). Run once as master.
--
-- The cart now applies the same "visible product" rule as the catalog
-- (product, store and category active) and blocks sellers from adding their
-- own products, so app_cart needs to read a few columns of sellers and
-- categories. Read-only, column-level: nothing else is exposed.
-- =====================================================================

GRANT SELECT (id, user_id, is_active) ON marketplace_core.sellers    TO 'app_cart'@'%';
GRANT SELECT (id, is_active)          ON marketplace_core.categories TO 'app_cart'@'%';

-- Check:
SHOW GRANTS FOR 'app_cart'@'%';
