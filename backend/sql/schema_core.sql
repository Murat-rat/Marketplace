-- =====================================================================
-- Marketplace - RDS MySQL #1: CORE BUSINESS
-- Tables: users, sellers, categories, products, product_images,
--         addresses, orders, shipments, order_items
-- Requires MySQL 8.0.16+ (CHECK constraints are enforced from that version)
-- =====================================================================

-- OPTIONAL: uncomment to wipe an old schema (this deletes ALL its data).
-- DROP DATABASE IF EXISTS marketplace_core;

CREATE DATABASE IF NOT EXISTS marketplace_core
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE marketplace_core;

-- ---------------------------------------------------------------------
-- users
-- Passwords and cards live in the sensitive database (RDS #2).
-- ---------------------------------------------------------------------
CREATE TABLE users (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  name        VARCHAR(80)  NOT NULL,
  email       VARCHAR(100) NOT NULL,
  phone       VARCHAR(15),
  role        ENUM('buyer', 'admin') NOT NULL DEFAULT 'buyer',
  is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_users_email UNIQUE (email)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- sellers (a user has at most one seller profile)
-- ---------------------------------------------------------------------
CREATE TABLE sellers (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  user_id     INT          NOT NULL,
  store_name  VARCHAR(60)  NOT NULL,
  description TEXT,
  is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_sellers_user UNIQUE (user_id),
  CONSTRAINT fk_sellers_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- categories (self-referencing for hierarchies, e.g. Electronics > Phones)
-- ---------------------------------------------------------------------
CREATE TABLE categories (
  id                 INT AUTO_INCREMENT PRIMARY KEY,
  parent_category_id INT         NULL,
  name               VARCHAR(50) NOT NULL,
  is_active          BOOLEAN     NOT NULL DEFAULT TRUE,
  CONSTRAINT fk_categories_parent FOREIGN KEY (parent_category_id)
    REFERENCES categories(id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- products
-- average_rating / review_count are denormalized from the reviews that
-- live in DynamoDB (t_review); the application updates them on each review.
-- ---------------------------------------------------------------------
CREATE TABLE products (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  seller_id      INT           NOT NULL,
  category_id    INT           NOT NULL,
  name           VARCHAR(120)  NOT NULL,
  description    TEXT,
  price          DECIMAL(10,2) NOT NULL,
  stock          INT           NOT NULL DEFAULT 0,
  average_rating DECIMAL(2,1)  NOT NULL DEFAULT 0.0,
  review_count   INT           NOT NULL DEFAULT 0,
  is_active      BOOLEAN       NOT NULL DEFAULT TRUE,
  published_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_products_seller   FOREIGN KEY (seller_id)   REFERENCES sellers(id),
  CONSTRAINT fk_products_category FOREIGN KEY (category_id) REFERENCES categories(id),
  CONSTRAINT chk_products_price CHECK (price >= 0),
  CONSTRAINT chk_products_stock CHECK (stock >= 0),
  INDEX idx_products_seller (seller_id),
  INDEX idx_products_category (category_id),
  FULLTEXT INDEX ft_products_search (name, description)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- product_images (files are stored in S3; only the URL is kept here)
-- ---------------------------------------------------------------------
CREATE TABLE product_images (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  product_id  INT          NOT NULL,
  url         VARCHAR(255) NOT NULL,
  is_primary  BOOLEAN      NOT NULL DEFAULT FALSE,
  sort_order  INT          NOT NULL DEFAULT 0,
  CONSTRAINT fk_images_product FOREIGN KEY (product_id)
    REFERENCES products(id) ON DELETE CASCADE,
  INDEX idx_images_product (product_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- addresses (saved addresses of a user)
-- ---------------------------------------------------------------------
CREATE TABLE addresses (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  user_id      INT          NOT NULL,
  label        VARCHAR(30),
  address_line VARCHAR(255) NOT NULL,
  city         VARCHAR(60)  NOT NULL,
  postal_code  VARCHAR(10)  NOT NULL,
  is_default   BOOLEAN      NOT NULL DEFAULT FALSE,
  CONSTRAINT fk_addresses_user FOREIGN KEY (user_id)
    REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_addresses_user (user_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- orders
-- shipping_address is a snapshot copy taken at purchase time.
-- Checkout order: create 'pending' -> register payment (RDS #2)
--                 -> set 'paid' and decrement stock.
-- ---------------------------------------------------------------------
CREATE TABLE orders (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  user_id          INT           NOT NULL,
  total            DECIMAL(10,2) NOT NULL,
  status           ENUM('pending', 'paid', 'shipped', 'delivered', 'cancelled')
                   NOT NULL DEFAULT 'pending',
  shipping_address VARCHAR(255)  NOT NULL,
  created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT chk_orders_total CHECK (total >= 0),
  INDEX idx_orders_user_date (user_id, created_at)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- shipments (one order can have several shipments, e.g. one per seller)
-- ---------------------------------------------------------------------
CREATE TABLE shipments (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  order_id        INT         NOT NULL,
  carrier         VARCHAR(50),
  tracking_number VARCHAR(30),
  status          ENUM('preparing', 'shipped', 'in_transit', 'delivered', 'returned')
                  NOT NULL DEFAULT 'preparing',
  shipped_at      DATETIME    NULL,
  CONSTRAINT fk_shipments_order FOREIGN KEY (order_id) REFERENCES orders(id),
  INDEX idx_shipments_order (order_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- order_items
-- unit_price keeps the price at purchase time.
-- seller_id lets each seller see and manage only their own sales.
-- shipment_id is NULL until the item is assigned to a shipment.
-- ---------------------------------------------------------------------
CREATE TABLE order_items (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  order_id    INT           NOT NULL,
  product_id  INT           NOT NULL,
  seller_id   INT           NOT NULL,
  shipment_id INT           NULL,
  quantity    INT           NOT NULL,
  unit_price  DECIMAL(10,2) NOT NULL,
  status      ENUM('pending', 'confirmed', 'shipped', 'delivered', 'cancelled')
              NOT NULL DEFAULT 'pending',
  CONSTRAINT fk_items_order    FOREIGN KEY (order_id)    REFERENCES orders(id) ON DELETE CASCADE,
  CONSTRAINT fk_items_product  FOREIGN KEY (product_id)  REFERENCES products(id),
  CONSTRAINT fk_items_seller   FOREIGN KEY (seller_id)   REFERENCES sellers(id),
  CONSTRAINT fk_items_shipment FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE SET NULL,
  CONSTRAINT chk_items_quantity CHECK (quantity > 0),
  CONSTRAINT chk_items_price    CHECK (unit_price >= 0),
  INDEX idx_items_order (order_id),
  INDEX idx_items_product (product_id),
  INDEX idx_items_seller (seller_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Atomic stock decrement (use inside the checkout transaction).
-- If it affects 0 rows, there was not enough stock: roll back.
--
--   UPDATE products
--      SET stock = stock - %s
--    WHERE id = %s AND stock >= %s;
-- ---------------------------------------------------------------------
