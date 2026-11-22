-- =====================================================================
-- Self-checking test for migration 002 (the three stored procedures).
-- Run as the RDS master user on RDS #1, AFTER 002_stored_procedures.sql.
--
-- It creates its own test users/sellers/products (emails sp.test.*@example.com,
-- category "SP Test Category"), runs every case, prints one row per check with
-- passed = 1/0, and then deletes everything it created. Real data is not touched,
-- except that the test rows briefly exist while it runs.
-- Expected result: every row has passed = 1.
-- =====================================================================

USE marketplace_core;

DELIMITER $$

-- ---------- helpers: call a procedure and capture its error code ----------
DROP PROCEDURE IF EXISTS sp_test_try_place $$
CREATE PROCEDURE sp_test_try_place(IN u INT, IN a INT, IN items JSON, OUT o_err VARCHAR(128), OUT o_order INT)
BEGIN
  DECLARE CONTINUE HANDLER FOR SQLEXCEPTION GET STACKED DIAGNOSTICS CONDITION 1 o_err = MESSAGE_TEXT;
  SET o_err = NULL, o_order = NULL;
  CALL sp_place_order(u, a, items, o_order, @sp_test_total);
END $$

DROP PROCEDURE IF EXISTS sp_test_try_cancel $$
CREATE PROCEDURE sp_test_try_cancel(IN o INT, IN u INT, OUT o_err VARCHAR(128), OUT o_paid BOOLEAN)
BEGIN
  DECLARE CONTINUE HANDLER FOR SQLEXCEPTION GET STACKED DIAGNOSTICS CONDITION 1 o_err = MESSAGE_TEXT;
  SET o_err = NULL, o_paid = NULL;
  CALL sp_cancel_order(o, u, o_paid);
END $$

DROP PROCEDURE IF EXISTS sp_test_try_ship $$
CREATE PROCEDURE sp_test_try_ship(IN s INT, IN sh INT, IN st VARCHAR(20), IN carrier VARCHAR(50),
                                  IN tracking VARCHAR(30), OUT o_err VARCHAR(128), OUT o_status VARCHAR(20))
BEGIN
  DECLARE CONTINUE HANDLER FOR SQLEXCEPTION GET STACKED DIAGNOSTICS CONDITION 1 o_err = MESSAGE_TEXT;
  SET o_err = NULL, o_status = NULL;
  CALL sp_update_shipment_status(s, sh, st, carrier, tracking, o_status);
END $$

DROP PROCEDURE IF EXISTS sp_test_cleanup $$
CREATE PROCEDURE sp_test_cleanup()
BEGIN
  DELETE oi FROM order_items oi JOIN orders o ON o.id = oi.order_id JOIN users u ON u.id = o.user_id
   WHERE u.email LIKE 'sp.test.%@example.com';
  DELETE sh FROM shipments sh JOIN orders o ON o.id = sh.order_id JOIN users u ON u.id = o.user_id
   WHERE u.email LIKE 'sp.test.%@example.com';
  DELETE o FROM orders o JOIN users u ON u.id = o.user_id WHERE u.email LIKE 'sp.test.%@example.com';
  DELETE p FROM products p JOIN categories c ON c.id = p.category_id WHERE c.name = 'SP Test Category';
  DELETE FROM categories WHERE name = 'SP Test Category';
  DELETE a FROM addresses a JOIN users u ON u.id = a.user_id WHERE u.email LIKE 'sp.test.%@example.com';
  DELETE s FROM sellers s JOIN users u ON u.id = s.user_id WHERE u.email LIKE 'sp.test.%@example.com';
  DELETE FROM users WHERE email LIKE 'sp.test.%@example.com';
END $$

-- ---------- the test ----------
DROP PROCEDURE IF EXISTS sp_test_run $$
CREATE PROCEDURE sp_test_run()
BEGIN
  DECLARE v_buyer, v_other, v_owner1, v_owner2, v_seller1, v_seller2 INT;
  DECLARE v_addr, v_addr_other, v_addr_owner1, v_cat INT;
  DECLARE v_p1, v_p2, v_p_inactive, v_p_empty INT;
  DECLARE v_order, v_order2, v_order3, v_ship1, v_ship2, v_n INT;
  DECLARE v_err VARCHAR(128);
  DECLARE v_status VARCHAR(20);
  DECLARE v_paid BOOLEAN;

  DROP TEMPORARY TABLE IF EXISTS sp_test_results;
  CREATE TEMPORARY TABLE sp_test_results (
    n INT AUTO_INCREMENT PRIMARY KEY, test VARCHAR(100), passed BOOLEAN, detail VARCHAR(128));

  -- ---------- test data ----------
  INSERT INTO users (name, email, role) VALUES ('SP Buyer', 'sp.test.buyer@example.com', 'buyer');
  SET v_buyer = LAST_INSERT_ID();
  INSERT INTO users (name, email, role) VALUES ('SP Other', 'sp.test.other@example.com', 'buyer');
  SET v_other = LAST_INSERT_ID();
  INSERT INTO users (name, email, role) VALUES ('SP Owner 1', 'sp.test.owner1@example.com', 'buyer');
  SET v_owner1 = LAST_INSERT_ID();
  INSERT INTO users (name, email, role) VALUES ('SP Owner 2', 'sp.test.owner2@example.com', 'buyer');
  SET v_owner2 = LAST_INSERT_ID();
  INSERT INTO sellers (user_id, store_name) VALUES (v_owner1, 'SP Store 1');
  SET v_seller1 = LAST_INSERT_ID();
  INSERT INTO sellers (user_id, store_name) VALUES (v_owner2, 'SP Store 2');
  SET v_seller2 = LAST_INSERT_ID();

  INSERT INTO addresses (user_id, address_line, city, postal_code) VALUES (v_buyer, 'Calle 1', 'Cuernavaca', '62000');
  SET v_addr = LAST_INSERT_ID();
  INSERT INTO addresses (user_id, address_line, city, postal_code) VALUES (v_other, 'Calle 2', 'Cuernavaca', '62000');
  SET v_addr_other = LAST_INSERT_ID();
  INSERT INTO addresses (user_id, address_line, city, postal_code) VALUES (v_owner1, 'Calle 3', 'Cuernavaca', '62000');
  SET v_addr_owner1 = LAST_INSERT_ID();

  INSERT INTO categories (parent_category_id, name) VALUES (NULL, 'SP Test Category');
  SET v_cat = LAST_INSERT_ID();
  INSERT INTO products (seller_id, category_id, name, price, stock) VALUES (v_seller1, v_cat, 'SP P1', 100.00, 5);
  SET v_p1 = LAST_INSERT_ID();
  INSERT INTO products (seller_id, category_id, name, price, stock) VALUES (v_seller2, v_cat, 'SP P2', 50.00, 2);
  SET v_p2 = LAST_INSERT_ID();
  INSERT INTO products (seller_id, category_id, name, price, stock, is_active) VALUES (v_seller1, v_cat, 'SP inactive', 10.00, 10, FALSE);
  SET v_p_inactive = LAST_INSERT_ID();
  INSERT INTO products (seller_id, category_id, name, price, stock) VALUES (v_seller1, v_cat, 'SP empty', 10.00, 0);
  SET v_p_empty = LAST_INSERT_ID();

  -- ---------- sp_place_order: rejected input ----------
  CALL sp_test_try_place(v_buyer, v_addr, JSON_ARRAY(), v_err, v_order);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('place: empty cart', v_err = 'INVALID_ITEMS', v_err);

  CALL sp_test_try_place(v_buyer, v_addr, JSON_ARRAY(JSON_OBJECT('product_id', v_p1, 'quantity', 0)), v_err, v_order);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('place: quantity 0', v_err = 'INVALID_ITEMS', v_err);

  CALL sp_test_try_place(v_buyer, v_addr, JSON_ARRAY(JSON_OBJECT('product_id', v_p1, 'quantity', 60),
                                                     JSON_OBJECT('product_id', v_p1, 'quantity', 60)), v_err, v_order);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('place: merged quantity over 100', v_err = 'INVALID_ITEMS', v_err);

  CALL sp_test_try_place(v_buyer, v_addr, JSON_ARRAY(JSON_OBJECT('product_id', 'x', 'quantity', 1)), v_err, v_order);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('place: non-numeric product id', v_err = 'INVALID_ITEMS', v_err);

  CALL sp_test_try_place(v_buyer, v_addr_other, JSON_ARRAY(JSON_OBJECT('product_id', v_p1, 'quantity', 1)), v_err, v_order);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('place: someone else''s address', v_err = 'ADDRESS_NOT_FOUND', v_err);

  CALL sp_test_try_place(v_buyer, v_addr, JSON_ARRAY(JSON_OBJECT('product_id', v_p_inactive, 'quantity', 1)), v_err, v_order);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('place: inactive product', v_err = 'PRODUCT_UNAVAILABLE', v_err);

  CALL sp_test_try_place(v_owner1, v_addr_owner1, JSON_ARRAY(JSON_OBJECT('product_id', v_p1, 'quantity', 1)), v_err, v_order);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('place: seller buys own product', v_err = 'OWN_PRODUCT', v_err);

  CALL sp_test_try_place(v_buyer, v_addr, JSON_ARRAY(JSON_OBJECT('product_id', v_p2, 'quantity', 1),
                                                     JSON_OBJECT('product_id', v_p1, 'quantity', 6)), v_err, v_order);
  SELECT stock INTO v_n FROM products WHERE id = v_p2;
  INSERT INTO sp_test_results (test, passed, detail)
  VALUES ('place: not enough stock, nothing changes',
          v_err = 'OUT_OF_STOCK' AND v_n = 2 AND NOT EXISTS (SELECT 1 FROM orders WHERE user_id = v_buyer), v_err);

  CALL sp_test_try_place(v_buyer, v_addr, JSON_ARRAY(JSON_OBJECT('product_id', v_p_empty, 'quantity', 1)), v_err, v_order);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('place: stock 0', v_err = 'OUT_OF_STOCK', v_err);

  -- ---------- sp_place_order: success (repeated line merged, 2 sellers) ----------
  CALL sp_test_try_place(v_buyer, v_addr, JSON_ARRAY(JSON_OBJECT('product_id', v_p1, 'quantity', 2),
                                                     JSON_OBJECT('product_id', v_p1, 'quantity', 1),
                                                     JSON_OBJECT('product_id', v_p2, 'quantity', 1)), v_err, v_order);
  INSERT INTO sp_test_results (test, passed, detail)
  VALUES ('place: order created, total from DB prices',
          v_err IS NULL AND (SELECT total FROM orders WHERE id = v_order) = 350.00
                        AND (SELECT status FROM orders WHERE id = v_order) = 'pending', v_err);
  INSERT INTO sp_test_results (test, passed, detail)
  VALUES ('place: stock reserved',
          (SELECT stock FROM products WHERE id = v_p1) = 2 AND (SELECT stock FROM products WHERE id = v_p2) = 1, NULL);
  INSERT INTO sp_test_results (test, passed, detail)
  VALUES ('place: 2 items, 1 shipment per seller',
          (SELECT COUNT(*) FROM order_items WHERE order_id = v_order) = 2
          AND (SELECT COUNT(*) FROM shipments WHERE order_id = v_order AND status = 'preparing') = 2
          AND (SELECT COUNT(DISTINCT shipment_id) FROM order_items WHERE order_id = v_order) = 2, NULL);

  -- ---------- sp_cancel_order ----------
  CALL sp_test_try_cancel(v_order, v_other, v_err, v_paid);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('cancel: someone else''s order', v_err = 'ORDER_NOT_FOUND', v_err);

  CALL sp_test_try_cancel(v_order, v_buyer, v_err, v_paid);
  INSERT INTO sp_test_results (test, passed, detail)
  VALUES ('cancel: own pending order, stock back',
          v_err IS NULL AND v_paid = FALSE
          AND (SELECT status FROM orders WHERE id = v_order) = 'cancelled'
          AND (SELECT stock FROM products WHERE id = v_p1) = 5 AND (SELECT stock FROM products WHERE id = v_p2) = 2
          AND NOT EXISTS (SELECT 1 FROM shipments WHERE order_id = v_order), v_err);

  CALL sp_test_try_cancel(v_order, v_buyer, v_err, v_paid);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('cancel: twice', v_err = 'ORDER_NOT_CANCELLABLE', v_err);

  -- ---------- sp_update_shipment_status ----------
  CALL sp_test_try_place(v_buyer, v_addr, JSON_ARRAY(JSON_OBJECT('product_id', v_p1, 'quantity', 1),
                                                     JSON_OBJECT('product_id', v_p2, 'quantity', 1)), v_err, v_order2);
  SELECT shipment_id INTO v_ship1 FROM order_items WHERE order_id = v_order2 AND seller_id = v_seller1;
  SELECT shipment_id INTO v_ship2 FROM order_items WHERE order_id = v_order2 AND seller_id = v_seller2;

  CALL sp_test_try_ship(v_seller1, v_ship1, 'shipped', 'DHL', 'TRK1', v_err, v_status);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('ship: order not paid yet', v_err = 'ORDER_NOT_PAID', v_err);

  -- What the checkout Lambda does after the mock payment is approved:
  UPDATE orders SET status = 'paid' WHERE id = v_order2 AND status = 'pending';
  UPDATE order_items SET status = 'confirmed' WHERE order_id = v_order2 AND status = 'pending';

  CALL sp_test_try_ship(v_seller2, v_ship1, 'shipped', 'DHL', 'TRK1', v_err, v_status);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('ship: another seller''s shipment', v_err = 'SHIPMENT_NOT_FOUND', v_err);

  CALL sp_test_try_ship(v_seller1, v_ship1, 'shipped', '  ', NULL, v_err, v_status);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('ship: missing carrier/tracking', v_err = 'CARRIER_REQUIRED', v_err);

  CALL sp_test_try_ship(v_seller1, v_ship1, 'delivered', NULL, NULL, v_err, v_status);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('ship: skip from preparing to delivered', v_err = 'INVALID_TRANSITION', v_err);

  CALL sp_test_try_ship(v_seller1, v_ship1, 'lost', NULL, NULL, v_err, v_status);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('ship: unknown status', v_err = 'INVALID_STATUS', v_err);

  CALL sp_test_try_ship(v_seller1, v_ship1, 'shipped', 'DHL', 'TRK1', v_err, v_status);
  INSERT INTO sp_test_results (test, passed, detail)
  VALUES ('ship: seller 1 ships, order shipped',
          v_err IS NULL AND v_status = 'shipped'
          AND (SELECT status FROM order_items WHERE order_id = v_order2 AND seller_id = v_seller1) = 'shipped'
          AND (SELECT status FROM order_items WHERE order_id = v_order2 AND seller_id = v_seller2) = 'confirmed'
          AND (SELECT shipped_at IS NOT NULL FROM shipments WHERE id = v_ship1), v_err);

  CALL sp_test_try_cancel(v_order2, v_buyer, v_err, v_paid);
  INSERT INTO sp_test_results (test, passed, detail) VALUES ('cancel: after a shipment left', v_err = 'ORDER_NOT_CANCELLABLE', v_err);

  CALL sp_test_try_ship(v_seller1, v_ship1, 'delivered', NULL, NULL, v_err, v_status);
  INSERT INTO sp_test_results (test, passed, detail)
  VALUES ('ship: seller 1 delivered, order still shipped', v_err IS NULL AND v_status = 'shipped', v_err);

  CALL sp_test_try_ship(v_seller2, v_ship2, 'shipped', 'FedEx', 'TRK2', v_err, v_status);
  CALL sp_test_try_ship(v_seller2, v_ship2, 'in_transit', NULL, NULL, v_err, v_status);
  CALL sp_test_try_ship(v_seller2, v_ship2, 'delivered', NULL, NULL, v_err, v_status);
  INSERT INTO sp_test_results (test, passed, detail)
  VALUES ('ship: all delivered, order delivered',
          v_err IS NULL AND v_status = 'delivered' AND (SELECT status FROM orders WHERE id = v_order2) = 'delivered', v_err);

  -- ---------- returned package puts stock back ----------
  CALL sp_test_try_place(v_buyer, v_addr, JSON_ARRAY(JSON_OBJECT('product_id', v_p1, 'quantity', 2)), v_err, v_order3);
  UPDATE orders SET status = 'paid' WHERE id = v_order3 AND status = 'pending';
  UPDATE order_items SET status = 'confirmed' WHERE order_id = v_order3 AND status = 'pending';
  SELECT shipment_id INTO v_ship1 FROM order_items WHERE order_id = v_order3;
  SELECT stock INTO v_n FROM products WHERE id = v_p1;
  CALL sp_test_try_ship(v_seller1, v_ship1, 'shipped', 'DHL', 'TRK3', v_err, v_status);
  CALL sp_test_try_ship(v_seller1, v_ship1, 'returned', NULL, NULL, v_err, v_status);
  INSERT INTO sp_test_results (test, passed, detail)
  VALUES ('ship: returned, stock back, order cancelled',
          v_err IS NULL AND v_status = 'cancelled' AND (SELECT stock FROM products WHERE id = v_p1) = v_n + 2, v_err);

  SELECT n, test, IF(passed, 1, 0) AS passed, detail AS error_code FROM sp_test_results ORDER BY n;
  SELECT SUM(passed = 1) AS passed, SUM(passed IS NULL OR passed = 0) AS failed FROM sp_test_results;
  DROP TEMPORARY TABLE IF EXISTS sp_test_results;
END $$

DELIMITER ;

CALL sp_test_cleanup();  -- leftovers of an interrupted earlier run
CALL sp_test_run();
CALL sp_test_cleanup();

DROP PROCEDURE IF EXISTS sp_test_run;
DROP PROCEDURE IF EXISTS sp_test_cleanup;
DROP PROCEDURE IF EXISTS sp_test_try_place;
DROP PROCEDURE IF EXISTS sp_test_try_cancel;
DROP PROCEDURE IF EXISTS sp_test_try_ship;
