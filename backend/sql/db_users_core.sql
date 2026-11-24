-- =====================================================================
-- RDS #1 (core business) - least-privilege MySQL users, one per Lambda.
--
-- In the Learner Lab every Lambda runs with the same LabRole, so IAM
-- cannot separate what each function may touch. These users do it at
-- the database level instead: a compromised Lambda can only reach the
-- tables (and columns) its job needs.
--
-- BEFORE RUNNING:
--   1. (Schema name already matches schema_core.sql: marketplace_core.)
--   2. Replace every CHANGE_ME_* with a long random password
--      (e.g. python -c "import secrets; print(secrets.token_urlsafe(24))").
--   3. Run it connected as the RDS master user.
--
-- Host '%' is acceptable only because the RDS instance is NOT publicly
-- accessible and its security group accepts traffic only from the
-- Lambda security group. You may narrow it to your VPC CIDR, e.g. '10.0.%'.
-- =====================================================================

-- ---------- auth: register + login ----------
CREATE USER IF NOT EXISTS 'app_auth'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT, INSERT, DELETE ON marketplace_core.users   TO 'app_auth'@'%';
GRANT UPDATE (email) ON marketplace_core.users TO 'app_auth'@'%';
GRANT SELECT, INSERT, DELETE ON marketplace_core.sellers TO 'app_auth'@'%';

-- ---------- catalog: read-only browsing ----------
CREATE USER IF NOT EXISTS 'app_catalog'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT ON marketplace_core.categories     TO 'app_catalog'@'%';
GRANT SELECT ON marketplace_core.products       TO 'app_catalog'@'%';
GRANT SELECT ON marketplace_core.product_images TO 'app_catalog'@'%';
GRANT SELECT (id, store_name, description, is_active) ON marketplace_core.sellers TO 'app_catalog'@'%';

-- ---------- cart: validates products before writing to DynamoDB ----------
CREATE USER IF NOT EXISTS 'app_cart'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT ON marketplace_core.products TO 'app_cart'@'%';
-- Only what is needed to know if a product is visible and who sells it.
GRANT SELECT (id, user_id, is_active) ON marketplace_core.sellers    TO 'app_cart'@'%';
GRANT SELECT (id, is_active)          ON marketplace_core.categories TO 'app_cart'@'%';

-- ---------- reviews: purchase check + rating fields only ----------
CREATE USER IF NOT EXISTS 'app_reviews'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT ON marketplace_core.orders      TO 'app_reviews'@'%';
GRANT SELECT ON marketplace_core.order_items TO 'app_reviews'@'%';
GRANT SELECT ON marketplace_core.products    TO 'app_reviews'@'%';
GRANT UPDATE (average_rating, review_count) ON marketplace_core.products TO 'app_reviews'@'%';

-- ---------- account: the user's own addresses ----------
CREATE USER IF NOT EXISTS 'app_account'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT, INSERT, UPDATE, DELETE ON marketplace_core.addresses TO 'app_account'@'%';

-- ---------- checkout: create orders, decrement stock ----------
-- Orders and stock are written only by sp_place_order / sp_cancel_order
-- (EXECUTE is granted in migrations/002_stored_procedures.sql).
CREATE USER IF NOT EXISTS 'app_checkout'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT ON marketplace_core.addresses TO 'app_checkout'@'%';
GRANT SELECT ON marketplace_core.products  TO 'app_checkout'@'%';
GRANT SELECT, UPDATE (status) ON marketplace_core.orders      TO 'app_checkout'@'%';
GRANT SELECT, UPDATE (status) ON marketplace_core.order_items TO 'app_checkout'@'%';

-- ---------- orders: shopper's order history (read-only) ----------
CREATE USER IF NOT EXISTS 'app_orders'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT ON marketplace_core.orders         TO 'app_orders'@'%';
GRANT SELECT ON marketplace_core.order_items    TO 'app_orders'@'%';
GRANT SELECT ON marketplace_core.shipments      TO 'app_orders'@'%';
GRANT SELECT ON marketplace_core.products       TO 'app_orders'@'%';
GRANT SELECT ON marketplace_core.product_images TO 'app_orders'@'%';

-- ---------- seller: products, images, fulfilment ----------
CREATE USER IF NOT EXISTS 'app_seller'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT, UPDATE ON marketplace_core.sellers          TO 'app_seller'@'%';
GRANT SELECT          ON marketplace_core.categories       TO 'app_seller'@'%';
GRANT SELECT, INSERT, UPDATE ON marketplace_core.products  TO 'app_seller'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE ON marketplace_core.product_images TO 'app_seller'@'%';
-- Fulfilment (shipments, item and order status) only through
-- sp_update_shipment_status (EXECUTE granted in migration 002).
GRANT SELECT ON marketplace_core.orders      TO 'app_seller'@'%';
GRANT SELECT ON marketplace_core.order_items TO 'app_seller'@'%';
GRANT SELECT ON marketplace_core.shipments   TO 'app_seller'@'%';

FLUSH PRIVILEGES;
