-- =====================================================================
-- Migration 002 - stored procedures for RDS #1 (marketplace_core).
-- Run ONCE as the RDS master user (MySQL Workbench understands DELIMITER).
-- Safe to re-run: every procedure is dropped and created again.
--
--   sp_place_order             checkout: validates the cart, locks the products,
--                              takes prices from the DB, reserves stock, creates
--                              the order, its items and one shipment per seller.
--   sp_cancel_order            buyer cancels an order that has not shipped yet,
--                              or checkout cancels it after a rejected payment;
--                              gives the stock back.
--   sp_update_shipment_status  a seller moves their own shipment forward and the
--                              order items / order status follow automatically.
--
-- Security
-- * SQL SECURITY DEFINER: the procedures run with the master's rights, so the
--   Lambda users only get EXECUTE on them. The end of this file REMOVES the
--   direct write permissions they replace (stock, order rows, shipments), so a
--   compromised Lambda cannot set stock or statuses to arbitrary values.
-- * Every procedure re-checks ownership (the user/seller id comes from the
--   JWT in the Lambda) and answers "not found" for other people's data.
-- * Errors are raised with SIGNAL SQLSTATE '45000' (MySQL error 1644) and a
--   short code in MESSAGE_TEXT, e.g. OUT_OF_STOCK. The Lambda maps the code to
--   an HTTP response; on any error the whole transaction is rolled back.
--
-- Calling them from a Lambda (pymysql), outside any other open transaction:
--   cur.execute("CALL sp_place_order(%s, %s, %s, @order_id, @total)",
--               (user_id, address_id, json.dumps(items)))
--   cur.execute("SELECT @order_id AS order_id, @total AS total")
-- =====================================================================

USE marketplace_core;

DELIMITER $$

-- ---------------------------------------------------------------------
-- sp_place_order
--   p_items: JSON array, e.g. [{"product_id": 7, "quantity": 2}, ...]
--            1-50 lines, quantity 1-100 per product (repeated products are merged).
--   Result:  order in status 'pending', items 'pending', shipments 'preparing'.
--            After the mock payment is approved, the checkout Lambda sets
--            orders.status = 'paid' and order_items.status = 'confirmed'
--            (WHERE status = 'pending'); if it is rejected it calls sp_cancel_order.
--   Errors:  INVALID_INPUT, INVALID_ITEMS, USER_NOT_FOUND, ADDRESS_NOT_FOUND,
--            OWN_PRODUCT, PRODUCT_UNAVAILABLE, OUT_OF_STOCK, TOTAL_TOO_LARGE
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_place_order $$
CREATE PROCEDURE sp_place_order(
  IN  p_user_id    INT,
  IN  p_address_id INT,
  IN  p_items      JSON,
  OUT p_order_id   INT,
  OUT p_total      DECIMAL(10,2))
  MODIFIES SQL DATA
  SQL SECURITY DEFINER
  COMMENT 'Creates a pending order, reserves stock and opens one shipment per seller'
BEGIN
  DECLARE v_address VARCHAR(255);
  DECLARE v_lines   INT DEFAULT 0;
  DECLARE v_count   INT DEFAULT 0;
  DECLARE v_total   DECIMAL(14,2);
  DECLARE v_seller  INT;

  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  SET p_order_id = NULL, p_total = NULL;

  -- ---------- validate the input ----------
  IF p_user_id IS NULL OR p_address_id IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'INVALID_INPUT';
  END IF;

  IF p_items IS NULL OR JSON_TYPE(p_items) <> 'ARRAY'
     OR JSON_LENGTH(p_items) NOT BETWEEN 1 AND 50 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'INVALID_ITEMS';
  END IF;

  -- Every line must be {"product_id": positive int, "quantity": 1..100}.
  SELECT COUNT(*) INTO v_count
    FROM JSON_TABLE(p_items, '$[*]' COLUMNS (
           product_id INT PATH '$.product_id' NULL ON EMPTY NULL ON ERROR,
           quantity   INT PATH '$.quantity'   NULL ON EMPTY NULL ON ERROR)) AS jt
   WHERE jt.product_id IS NULL OR jt.product_id < 1
      OR jt.quantity IS NULL OR jt.quantity NOT BETWEEN 1 AND 100;
  IF v_count > 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'INVALID_ITEMS';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM users WHERE id = p_user_id AND is_active) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'USER_NOT_FOUND';
  END IF;

  -- The address must belong to the buyer; it is copied into the order.
  SELECT LEFT(CONCAT_WS(', ', address_line, city, postal_code), 255) INTO v_address
    FROM addresses
   WHERE id = p_address_id AND user_id = p_user_id;
  IF v_address IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ADDRESS_NOT_FOUND';
  END IF;

  -- ---------- order lines (repeated products merged) ----------
  DROP TEMPORARY TABLE IF EXISTS tmp_order_lines;
  CREATE TEMPORARY TABLE tmp_order_lines (
    product_id  INT PRIMARY KEY,
    quantity    INT NOT NULL,
    unit_price  DECIMAL(10,2) NULL,
    seller_id   INT NULL,
    shipment_id INT NULL
  );
  INSERT INTO tmp_order_lines (product_id, quantity)
  SELECT jt.product_id, SUM(jt.quantity)
    FROM JSON_TABLE(p_items, '$[*]' COLUMNS (
           product_id INT PATH '$.product_id',
           quantity   INT PATH '$.quantity')) AS jt
   GROUP BY jt.product_id;

  SELECT COUNT(*), COALESCE(SUM(quantity > 100), 0) INTO v_lines, v_count FROM tmp_order_lines;
  IF v_count > 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'INVALID_ITEMS';
  END IF;

  START TRANSACTION;

  -- Lock the products being bought so two buyers cannot take the same unit.
  SELECT COUNT(*) INTO v_count
    FROM products p
    JOIN tmp_order_lines t ON t.product_id = p.id
     FOR UPDATE OF p;

  -- Sellers cannot buy their own products.
  SELECT COUNT(*) INTO v_count
    FROM tmp_order_lines t
    JOIN products p ON p.id = t.product_id
    JOIN sellers  s ON s.id = p.seller_id
   WHERE s.user_id = p_user_id;
  IF v_count > 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OWN_PRODUCT';
  END IF;

  -- Price and seller always come from the database, never from the client.
  -- Only visible products (product, seller and category active) can be bought.
  UPDATE tmp_order_lines t
    JOIN products   p ON p.id = t.product_id
    JOIN sellers    s ON s.id = p.seller_id
    JOIN categories c ON c.id = p.category_id
     SET t.unit_price = p.price,
         t.seller_id  = p.seller_id
   WHERE p.is_active AND s.is_active AND c.is_active;

  IF EXISTS (SELECT 1 FROM tmp_order_lines WHERE unit_price IS NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'PRODUCT_UNAVAILABLE';
  END IF;

  -- Atomic stock decrement: a row is only changed if it has enough stock.
  UPDATE products p
    JOIN tmp_order_lines t ON t.product_id = p.id
     SET p.stock = p.stock - t.quantity
   WHERE p.stock >= t.quantity;
  IF ROW_COUNT() <> v_lines THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OUT_OF_STOCK';
  END IF;

  SELECT SUM(quantity * unit_price) INTO v_total FROM tmp_order_lines;
  IF v_total > 99999999.99 THEN  -- orders.total is DECIMAL(10,2)
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'TOTAL_TOO_LARGE';
  END IF;

  INSERT INTO orders (user_id, total, status, shipping_address)
  VALUES (p_user_id, v_total, 'pending', v_address);
  SET p_order_id = LAST_INSERT_ID();

  -- One shipment per seller in the order.
  SET v_seller = (SELECT MIN(seller_id) FROM tmp_order_lines);
  WHILE v_seller IS NOT NULL DO
    INSERT INTO shipments (order_id, status) VALUES (p_order_id, 'preparing');
    UPDATE tmp_order_lines SET shipment_id = LAST_INSERT_ID() WHERE seller_id = v_seller;
    SET v_seller = (SELECT MIN(seller_id) FROM tmp_order_lines WHERE seller_id > v_seller);
  END WHILE;

  INSERT INTO order_items (order_id, product_id, seller_id, shipment_id, quantity, unit_price, status)
  SELECT p_order_id, product_id, seller_id, shipment_id, quantity, unit_price, 'pending'
    FROM tmp_order_lines;

  COMMIT;

  SET p_total = v_total;
  DROP TEMPORARY TABLE IF EXISTS tmp_order_lines;
END $$

-- ---------------------------------------------------------------------
-- sp_cancel_order
--   Only the buyer who owns the order, only while it is 'pending' or 'paid'
--   and no shipment has left yet. Restores stock, cancels the items, removes
--   the unshipped shipments and cancels the order.
--   p_was_paid = TRUE means the Lambda must mark the payment as 'refunded'
--   in RDS #2.
--   Errors: ORDER_NOT_FOUND, ORDER_NOT_CANCELLABLE
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_cancel_order $$
CREATE PROCEDURE sp_cancel_order(
  IN  p_order_id INT,
  IN  p_user_id  INT,
  OUT p_was_paid BOOLEAN)
  MODIFIES SQL DATA
  SQL SECURITY DEFINER
  COMMENT 'Cancels an unshipped order of the given buyer and restores the stock'
BEGIN
  DECLARE v_status VARCHAR(20);

  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  SET p_was_paid = FALSE;

  START TRANSACTION;

  -- Lock the order. Someone else's order looks exactly like a missing one.
  SELECT status INTO v_status
    FROM orders
   WHERE id = p_order_id AND user_id = p_user_id
     FOR UPDATE;
  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ORDER_NOT_FOUND';
  END IF;

  IF v_status NOT IN ('pending', 'paid')
     OR EXISTS (SELECT 1 FROM shipments WHERE order_id = p_order_id AND status <> 'preparing') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ORDER_NOT_CANCELLABLE';
  END IF;

  -- Give the reserved units back.
  UPDATE products p
    JOIN (SELECT product_id, SUM(quantity) AS qty
            FROM order_items
           WHERE order_id = p_order_id AND status <> 'cancelled'
           GROUP BY product_id) AS x ON x.product_id = p.id
     SET p.stock = p.stock + x.qty;

  UPDATE order_items
     SET status = 'cancelled', shipment_id = NULL
   WHERE order_id = p_order_id;

  DELETE FROM shipments WHERE order_id = p_order_id AND status = 'preparing';

  UPDATE orders SET status = 'cancelled' WHERE id = p_order_id;

  COMMIT;

  SET p_was_paid = (v_status = 'paid');
END $$

-- ---------------------------------------------------------------------
-- sp_update_shipment_status
--   Allowed moves:  preparing -> shipped            (carrier + tracking required)
--                   shipped   -> in_transit | delivered | returned
--                   in_transit-> delivered | returned
--   Items follow:   shipped/in_transit -> 'shipped', delivered -> 'delivered',
--                   returned -> 'cancelled' (and the stock goes back).
--   The order becomes 'shipped' when something is on its way, 'delivered'
--   when every remaining item arrived, 'cancelled' if everything came back.
--   Only for paid orders, and only the seller whose items are in the shipment.
--   p_order_status returns the order's new status.
--   Errors: INVALID_STATUS, SELLER_INACTIVE, SHIPMENT_NOT_FOUND,
--           ORDER_NOT_PAID, INVALID_TRANSITION, CARRIER_REQUIRED
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_update_shipment_status $$
CREATE PROCEDURE sp_update_shipment_status(
  IN  p_seller_id    INT,
  IN  p_shipment_id  INT,
  IN  p_new_status   VARCHAR(20),
  IN  p_carrier      VARCHAR(50),
  IN  p_tracking     VARCHAR(30),
  OUT p_order_status VARCHAR(20))
  MODIFIES SQL DATA
  SQL SECURITY DEFINER
  COMMENT 'Moves a seller''s shipment forward and updates its items and order'
BEGIN
  DECLARE v_current      VARCHAR(20);
  DECLARE v_order_id     INT;
  DECLARE v_order_status VARCHAR(20);
  DECLARE v_items        INT DEFAULT 0;
  DECLARE v_foreign      INT DEFAULT 0;
  DECLARE v_active       INT DEFAULT 0;
  DECLARE v_delivered    INT DEFAULT 0;
  DECLARE v_moving       INT DEFAULT 0;

  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  SET p_order_status = NULL;

  IF p_new_status IS NULL OR p_new_status NOT IN ('shipped', 'in_transit', 'delivered', 'returned') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'INVALID_STATUS';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM sellers WHERE id = p_seller_id AND is_active) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SELLER_INACTIVE';
  END IF;

  START TRANSACTION;

  SELECT sh.status, sh.order_id, o.status
    INTO v_current, v_order_id, v_order_status
    FROM shipments sh
    JOIN orders o ON o.id = sh.order_id
   WHERE sh.id = p_shipment_id
     FOR UPDATE;

  -- The shipment must hold items and ALL of them must be this seller's.
  -- Another seller's shipment gets the same answer as a missing one.
  SELECT COUNT(*), COALESCE(SUM(seller_id <> p_seller_id), 0)
    INTO v_items, v_foreign
    FROM order_items
   WHERE shipment_id = p_shipment_id;
  IF v_current IS NULL OR v_items = 0 OR v_foreign > 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'SHIPMENT_NOT_FOUND';
  END IF;

  IF v_order_status NOT IN ('paid', 'shipped') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'ORDER_NOT_PAID';
  END IF;

  IF NOT (   (v_current = 'preparing'  AND p_new_status = 'shipped')
          OR (v_current = 'shipped'    AND p_new_status IN ('in_transit', 'delivered', 'returned'))
          OR (v_current = 'in_transit' AND p_new_status IN ('delivered', 'returned'))) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'INVALID_TRANSITION';
  END IF;

  IF p_new_status = 'shipped'
     AND (NULLIF(TRIM(p_carrier), '') IS NULL OR NULLIF(TRIM(p_tracking), '') IS NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CARRIER_REQUIRED';
  END IF;

  UPDATE shipments
     SET status          = p_new_status,
         carrier         = IF(p_new_status = 'shipped', TRIM(p_carrier),  carrier),
         tracking_number = IF(p_new_status = 'shipped', TRIM(p_tracking), tracking_number),
         shipped_at      = IF(p_new_status = 'shipped', NOW(),            shipped_at)
   WHERE id = p_shipment_id;

  -- A returned package puts its units back in stock.
  IF p_new_status = 'returned' THEN
    UPDATE products p
      JOIN (SELECT product_id, SUM(quantity) AS qty
              FROM order_items
             WHERE shipment_id = p_shipment_id AND status <> 'cancelled'
             GROUP BY product_id) AS x ON x.product_id = p.id
       SET p.stock = p.stock + x.qty;
  END IF;

  UPDATE order_items
     SET status = CASE p_new_status
                    WHEN 'delivered' THEN 'delivered'
                    WHEN 'returned'  THEN 'cancelled'
                    ELSE 'shipped'
                  END
   WHERE shipment_id = p_shipment_id AND status <> 'cancelled';

  -- Recompute the order status from all of its items.
  SELECT COALESCE(SUM(status <> 'cancelled'), 0),
         COALESCE(SUM(status = 'delivered'), 0),
         COALESCE(SUM(status IN ('shipped', 'delivered')), 0)
    INTO v_active, v_delivered, v_moving
    FROM order_items
   WHERE order_id = v_order_id;

  SET p_order_status = CASE
                         WHEN v_active = 0           THEN 'cancelled'
                         WHEN v_delivered = v_active THEN 'delivered'
                         WHEN v_moving > 0           THEN 'shipped'
                         ELSE 'paid'
                       END;
  UPDATE orders SET status = p_order_status WHERE id = v_order_id;

  COMMIT;
END $$

DELIMITER ;

-- ---------------------------------------------------------------------
-- Permissions: the Lambdas may run the procedures, and lose the direct
-- write rights the procedures replace. (IF EXISTS: no error if a right
-- was never granted, e.g. on a fresh setup from db_users_core.sql.)
-- ---------------------------------------------------------------------
GRANT EXECUTE ON PROCEDURE marketplace_core.sp_place_order            TO 'app_checkout'@'%';
GRANT EXECUTE ON PROCEDURE marketplace_core.sp_cancel_order           TO 'app_checkout'@'%';
GRANT EXECUTE ON PROCEDURE marketplace_core.sp_cancel_order           TO 'app_orders'@'%';
GRANT EXECUTE ON PROCEDURE marketplace_core.sp_update_shipment_status TO 'app_seller'@'%';

-- checkout: stock and order rows only through sp_place_order / sp_cancel_order.
-- It keeps UPDATE(status) to mark an order 'paid' and its items 'confirmed'.
REVOKE IF EXISTS UPDATE (stock) ON marketplace_core.products    FROM 'app_checkout'@'%' IGNORE UNKNOWN USER;
REVOKE IF EXISTS INSERT         ON marketplace_core.orders      FROM 'app_checkout'@'%' IGNORE UNKNOWN USER;
REVOKE IF EXISTS INSERT         ON marketplace_core.order_items FROM 'app_checkout'@'%' IGNORE UNKNOWN USER;
GRANT UPDATE (status) ON marketplace_core.orders      TO 'app_checkout'@'%';
GRANT UPDATE (status) ON marketplace_core.order_items TO 'app_checkout'@'%';

-- seller: fulfilment only through sp_update_shipment_status.
REVOKE IF EXISTS UPDATE (status)      ON marketplace_core.orders      FROM 'app_seller'@'%' IGNORE UNKNOWN USER;
REVOKE IF EXISTS UPDATE (shipment_id) ON marketplace_core.order_items FROM 'app_seller'@'%' IGNORE UNKNOWN USER;
REVOKE IF EXISTS INSERT, UPDATE       ON marketplace_core.shipments   FROM 'app_seller'@'%' IGNORE UNKNOWN USER;

-- Check what was created:
SELECT ROUTINE_NAME, SECURITY_TYPE, ROUTINE_COMMENT
  FROM information_schema.ROUTINES
 WHERE ROUTINE_SCHEMA = 'marketplace_core' AND ROUTINE_TYPE = 'PROCEDURE';
