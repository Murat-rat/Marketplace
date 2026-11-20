-- =====================================================================
-- Demo catalog for RDS #1 (marketplace_core). Run ONCE as the master user.
--
-- Creates a category tree, a "Demo Store" seller and 14 products so the
-- catalog screens have something to show. The demo owner has no row in
-- `credentials`, so nobody can sign in as it.
-- Some products have stock 0 on purpose, to show "Out of stock".
-- =====================================================================

USE marketplace_core;

START TRANSACTION;

-- ---------- categories (parents first) ----------
INSERT INTO categories (parent_category_id, name) VALUES
  (NULL, 'Electronics'), (NULL, 'Home'), (NULL, 'Books'), (NULL, 'Sports');

SET @electronics = (SELECT id FROM categories WHERE name = 'Electronics' AND parent_category_id IS NULL ORDER BY id DESC LIMIT 1);
SET @home        = (SELECT id FROM categories WHERE name = 'Home'        AND parent_category_id IS NULL ORDER BY id DESC LIMIT 1);
SET @books       = (SELECT id FROM categories WHERE name = 'Books'       AND parent_category_id IS NULL ORDER BY id DESC LIMIT 1);
SET @sports      = (SELECT id FROM categories WHERE name = 'Sports'      AND parent_category_id IS NULL ORDER BY id DESC LIMIT 1);

INSERT INTO categories (parent_category_id, name) VALUES
  (@electronics, 'Phones'), (@electronics, 'Laptops'), (@electronics, 'Audio'),
  (@home, 'Kitchen'), (@home, 'Furniture'),
  (@books, 'Programming'), (@books, 'Novels'),
  (@sports, 'Fitness'), (@sports, 'Cycling');

SET @phones      = (SELECT id FROM categories WHERE name = 'Phones'      AND parent_category_id = @electronics);
SET @laptops     = (SELECT id FROM categories WHERE name = 'Laptops'     AND parent_category_id = @electronics);
SET @audio       = (SELECT id FROM categories WHERE name = 'Audio'       AND parent_category_id = @electronics);
SET @kitchen     = (SELECT id FROM categories WHERE name = 'Kitchen'     AND parent_category_id = @home);
SET @furniture   = (SELECT id FROM categories WHERE name = 'Furniture'   AND parent_category_id = @home);
SET @programming = (SELECT id FROM categories WHERE name = 'Programming' AND parent_category_id = @books);
SET @novels      = (SELECT id FROM categories WHERE name = 'Novels'      AND parent_category_id = @books);
SET @fitness     = (SELECT id FROM categories WHERE name = 'Fitness'     AND parent_category_id = @sports);
SET @cycling     = (SELECT id FROM categories WHERE name = 'Cycling'     AND parent_category_id = @sports);

-- ---------- demo seller (cannot log in: no credentials row) ----------
INSERT INTO users (name, email, phone, role) VALUES ('Demo Store Owner', 'demo.store@example.com', NULL, 'buyer');
SET @demo_user = LAST_INSERT_ID();
INSERT INTO sellers (user_id, store_name, description)
VALUES (@demo_user, 'Demo Store', 'Sample products used to try out the marketplace.');
SET @demo_seller = LAST_INSERT_ID();

-- ---------- products ----------
INSERT INTO products (seller_id, category_id, name, description, price, stock) VALUES
  (@demo_seller, @phones,      'Nova X5 Smartphone',          'Six-inch OLED screen, 128 GB storage and a dual camera. Unlocked for any carrier.', 6499.00, 12),
  (@demo_seller, @phones,      'Nova Lite Smartphone',        'Affordable phone with a large battery that lasts two days.',                       3299.00, 0),
  (@demo_seller, @laptops,     'AirBook 14 Laptop',           '14-inch laptop, 16 GB RAM, 512 GB SSD. Light enough for school every day.',        15999.00, 5),
  (@demo_seller, @laptops,     'ProStation 16 Laptop',        '16-inch workstation for programming and video editing.',                           28999.00, 2),
  (@demo_seller, @audio,       'Wireless Noise-Cancelling Headphones', 'Over-ear headphones with 30 hours of battery and active noise cancelling.', 2199.00, 20),
  (@demo_seller, @audio,       'Bluetooth Pocket Speaker',    'Water-resistant speaker that fits in your backpack.',                              699.00, 35),
  (@demo_seller, @kitchen,     'Stainless Steel Coffee Maker','Brews 12 cups with a programmable timer.',                                         1299.00, 8),
  (@demo_seller, @kitchen,     'Non-Stick Frying Pan Set',    'Three pans (20, 24 and 28 cm), safe for all stovetops.',                           899.00, 0),
  (@demo_seller, @furniture,   'Ergonomic Desk Chair',        'Adjustable height, lumbar support and breathable mesh back.',                      3499.00, 4),
  (@demo_seller, @programming, 'Python for Beginners',        'A friendly introduction to programming with Python, with exercises.',              459.00, 25),
  (@demo_seller, @programming, 'Designing Data Systems',      'How databases, caches and queues fit together in real applications.',              899.00, 10),
  (@demo_seller, @novels,      'The Silent Harbor',           'A mystery novel set in a small fishing town.',                                     299.00, 15),
  (@demo_seller, @fitness,     'Adjustable Dumbbell Pair',    'From 2 to 24 kg each with a quick-change dial.',                                   4299.00, 3),
  (@demo_seller, @cycling,     'City Bike Helmet',            'Lightweight helmet with a rear LED light.',                                         749.00, 18);

COMMIT;
