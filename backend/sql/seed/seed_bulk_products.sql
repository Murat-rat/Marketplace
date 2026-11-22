-- =====================================================================
-- Bulk sample products for RDS #1 (marketplace_core). Run as the master user.
--
-- Generates @how_many products in ONE INSERT ... SELECT (no loops, no
-- thousands of INSERT lines), spread over 12 demo stores and the 9
-- subcategories created by seed_catalog.sql. Run seed_catalog.sql first.
--
-- * Safe to run several times: each run ADDS @how_many more products and
--   continues the numbering, so names do not repeat.
-- * Takes a few seconds for 5,000-17,000 rows.
-- * About 8% of the products get stock 0 ("Out of stock").
-- * The demo store owners have no credentials row, so nobody can sign in as them.
--
-- Tip: try it first with @how_many = 50, check the result, then run the big one.
-- =====================================================================

USE marketplace_core;

-- How many products to ADD in this run (e.g. 5000 now, 17000 for the final data).
SET @how_many = 50;

-- The number generator below is a recursive CTE; allow it to go deep enough.
SET SESSION cte_max_recursion_depth = 100000;

START TRANSACTION;

-- ---------- 12 demo stores (created only once) ----------
INSERT INTO users (name, email, phone, role)
WITH RECURSIVE s (i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM s WHERE i < 12)
SELECT CONCAT(ELT(i, 'TechNova', 'HomeNest', 'PageTurner', 'PeakGear', 'ByteHub', 'UrbanCook',
                     'SoundWave', 'ReadMore', 'FitLab', 'WheelWorks', 'CasaViva', 'GadgetPoint'), ' Owner'),
       CONCAT('store', LPAD(i, 2, '0'), '.demo@example.com'), NULL, 'buyer'
FROM s
WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.email = CONCAT('store', LPAD(s.i, 2, '0'), '.demo@example.com'));

INSERT INTO sellers (user_id, store_name, description)
SELECT u.id,
       ELT(CAST(SUBSTRING(u.email, 6, 2) AS UNSIGNED),
           'TechNova', 'HomeNest', 'PageTurner', 'PeakGear', 'ByteHub', 'UrbanCook',
           'SoundWave', 'ReadMore', 'FitLab', 'WheelWorks', 'CasaViva', 'GadgetPoint'),
       'Demo store with generated sample products.'
FROM users u
WHERE u.email LIKE 'store__.demo@example.com'
  AND NOT EXISTS (SELECT 1 FROM sellers s WHERE s.user_id = u.id);

-- ---------- lookup tables for this run ----------
DROP TEMPORARY TABLE IF EXISTS tmp_sellers;
CREATE TEMPORARY TABLE tmp_sellers (k INT PRIMARY KEY, id INT NOT NULL);
INSERT INTO tmp_sellers (k, id)
SELECT ROW_NUMBER() OVER (ORDER BY s.id), s.id
FROM sellers s JOIN users u ON u.id = s.user_id
WHERE u.email LIKE 'store__.demo@example.com';

SET @n_sellers = (SELECT COUNT(*) FROM tmp_sellers);
-- Continue numbering after the products generated in earlier runs.
SET @offset = (SELECT COUNT(*) FROM products p WHERE p.seller_id IN (SELECT id FROM tmp_sellers));

-- k = subcategory number used below; lo/hi = price range in that subcategory.
DROP TEMPORARY TABLE IF EXISTS tmp_cats;
CREATE TEMPORARY TABLE tmp_cats (k INT PRIMARY KEY, id INT NOT NULL, lo INT NOT NULL, hi INT NOT NULL);
INSERT INTO tmp_cats (k, id, lo, hi)
SELECT v.k, MIN(c.id), v.lo, v.hi
FROM (          SELECT 1 AS k, 'Electronics' AS parent, 'Phones' AS name, 2500 AS lo, 32000 AS hi
      UNION ALL SELECT 2, 'Electronics', 'Laptops',     7000, 45000
      UNION ALL SELECT 3, 'Electronics', 'Audio',        300,  9000
      UNION ALL SELECT 4, 'Home',        'Kitchen',      200,  6000
      UNION ALL SELECT 5, 'Home',        'Furniture',    800, 18000
      UNION ALL SELECT 6, 'Books',       'Programming',  250,  1500
      UNION ALL SELECT 7, 'Books',       'Novels',       150,   700
      UNION ALL SELECT 8, 'Sports',      'Fitness',      150,  9000
      UNION ALL SELECT 9, 'Sports',      'Cycling',      200, 25000) AS v
JOIN categories p ON p.name = v.parent AND p.parent_category_id IS NULL
JOIN categories c ON c.parent_category_id = p.id AND c.name = v.name
GROUP BY v.k, v.lo, v.hi;

-- ---------- products ----------
-- n = product number, k = subcategory (1..9), m = position inside that subcategory.
-- Names combine 6 x 6 x 5 word lists per subcategory plus a series number,
-- so every generated name is different.
INSERT INTO products (seller_id, category_id, name, description, price, stock, published_at)
WITH RECURSIVE seq (n) AS (
  SELECT @offset
  UNION ALL
  SELECT n + 1 FROM seq WHERE n < @offset + @how_many - 1
),
g AS (SELECT n, n % 9 + 1 AS k, n DIV 9 AS m FROM seq),
w AS (
  SELECT n, k, m DIV 180 + 1 AS series,
    CASE k
      WHEN 1 THEN ELT(m % 6 + 1, 'Nova', 'Orion', 'Zenix', 'Pulse', 'Vertex', 'Lumo')
      WHEN 2 THEN ELT(m % 6 + 1, 'AirBook', 'ProStation', 'Nimbus', 'Atlas', 'Vertex', 'Zenix')
      WHEN 3 THEN ELT(m % 6 + 1, 'SoundWave', 'Bassline', 'Echo', 'Sonic', 'Aria', 'Tempo')
      WHEN 4 THEN ELT(m % 6 + 1, 'HomeChef', 'Cucina', 'SteelCraft', 'FreshPro', 'Aroma', 'Bistro')
      WHEN 5 THEN ELT(m % 6 + 1, 'Oakline', 'Nordic', 'Loft', 'Habitat', 'Comfy', 'Urban')
      WHEN 6 THEN ELT(m % 6 + 1, 'Learning', 'Mastering', 'Practical', 'Modern', 'Effective', 'Hands-On')
      WHEN 7 THEN ELT(m % 6 + 1, 'The Silent', 'The Last', 'The Hidden', 'The Broken', 'The Golden', 'The Distant')
      WHEN 8 THEN ELT(m % 6 + 1, 'IronCore', 'FitLab', 'PowerMax', 'FlexPro', 'Titan', 'Motion')
      ELSE        ELT(m % 6 + 1, 'WheelWorks', 'Velo', 'Trailblazer', 'Spoke', 'Ridge', 'Swift')
    END AS a,
    CASE k
      WHEN 1 THEN ELT((m DIV 6) % 6 + 1, 'Smartphone', 'Phone', 'Mini Phone', 'Flip Phone', 'Rugged Phone', '5G Phone')
      WHEN 2 THEN ELT((m DIV 6) % 6 + 1, 'Laptop', 'Ultrabook', 'Gaming Laptop', '2-in-1 Laptop', 'Chromebook', 'Workstation')
      WHEN 3 THEN ELT((m DIV 6) % 6 + 1, 'Headphones', 'Earbuds', 'Speaker', 'Soundbar', 'Turntable', 'Microphone')
      WHEN 4 THEN ELT((m DIV 6) % 6 + 1, 'Coffee Maker', 'Blender', 'Frying Pan', 'Knife Set', 'Toaster', 'Kettle')
      WHEN 5 THEN ELT((m DIV 6) % 6 + 1, 'Desk Chair', 'Bookshelf', 'Coffee Table', 'Desk', 'Sofa', 'Bed Frame')
      WHEN 6 THEN ELT((m DIV 6) % 6 + 1, 'Python', 'SQL', 'JavaScript', 'Java', 'Cloud Computing', 'Data Science')
      WHEN 7 THEN ELT((m DIV 6) % 6 + 1, 'Harbor', 'Garden', 'Kingdom', 'Letter', 'Mountain', 'River')
      WHEN 8 THEN ELT((m DIV 6) % 6 + 1, 'Dumbbell Set', 'Yoga Mat', 'Kettlebell', 'Resistance Bands', 'Jump Rope', 'Exercise Bike')
      ELSE        ELT((m DIV 6) % 6 + 1, 'Bike Helmet', 'Bike Light', 'Water Bottle', 'Bike Lock', 'Cycling Gloves', 'Road Bike')
    END AS b,
    CASE k
      WHEN 1 THEN ELT((m DIV 36) % 5 + 1, 'Lite', 'Plus', 'Pro', 'Max', 'Ultra')
      WHEN 2 THEN ELT((m DIV 36) % 5 + 1, '13', '14', '15', '16', '17')
      WHEN 3 THEN ELT((m DIV 36) % 5 + 1, 'Wireless', 'Studio', 'Sport', 'Mini', 'Max')
      WHEN 4 THEN ELT((m DIV 36) % 5 + 1, 'Classic', 'Deluxe', 'Compact', 'Pro', 'Family')
      WHEN 5 THEN ELT((m DIV 36) % 5 + 1, 'Oak', 'Walnut', 'White', 'Black', 'Grey')
      WHEN 6 THEN ELT((m DIV 36) % 5 + 1, 'Fundamentals', 'in Action', 'Cookbook', 'Patterns', 'for Beginners')
      WHEN 7 THEN ELT((m DIV 36) % 5 + 1, 'Novel', 'Saga', 'Chronicles', 'Mystery', 'Story')
      WHEN 8 THEN ELT((m DIV 36) % 5 + 1, 'Basic', 'Pro', 'Home', 'Elite', 'Compact')
      ELSE        ELT((m DIV 36) % 5 + 1, 'Sport', 'City', 'Trail', 'Race', 'Comfort')
    END AS c
  FROM g
)
SELECT ts.id,
       tc.id,
       CONCAT(w.a, ' ', w.b, ' ', w.c,
              CASE WHEN w.k IN (6, 7) THEN ' Vol. ' WHEN w.k IN (1, 2, 3) THEN ' Gen ' ELSE ' Model ' END,
              w.series),
       CONCAT(w.a, ' ', w.b, ', ', w.c, ' edition. ',
              ELT(w.n % 5 + 1, 'Great value for everyday use.', 'Built to last.', 'A customer favourite.',
                               'Ships within 48 hours.', 'Includes a one-year warranty.')),
       ROUND(tc.lo + RAND() * (tc.hi - tc.lo), 0),
       IF(RAND() < 0.08, 0, 1 + FLOOR(RAND() * 120)),
       NOW() - INTERVAL FLOOR(RAND() * 525600) MINUTE  -- sometime in the last year
FROM w
JOIN tmp_cats    tc ON tc.k = w.k
JOIN tmp_sellers ts ON ts.k = w.n % @n_sellers + 1;

SELECT ROW_COUNT() AS products_added;

COMMIT;

DROP TEMPORARY TABLE IF EXISTS tmp_sellers;
DROP TEMPORARY TABLE IF EXISTS tmp_cats;

-- Check: total products, and how many are out of stock.
SELECT COUNT(*) AS total_products, SUM(stock = 0) AS out_of_stock FROM products;

-- ---------------------------------------------------------------------
-- To REMOVE all generated products later (only works while none of them
-- has been ordered), run as master:
--
--   DELETE p FROM products p
--     JOIN sellers s ON s.id = p.seller_id
--     JOIN users u   ON u.id = s.user_id
--    WHERE u.email LIKE 'store__.demo@example.com';
-- ---------------------------------------------------------------------
