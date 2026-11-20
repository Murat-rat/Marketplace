-- =====================================================================
-- Marketplace - RDS MySQL #2: SENSITIVE DATA
-- Tables: credentials, cards, payments
-- Requires MySQL 8.0.16+ (CHECK constraints are enforced from that version)
--
-- Cross-database references (marked "logical FK" below) are NOT enforced
-- by MySQL: user_id points to marketplace_core.users on the OTHER RDS
-- instance, and order_id points to marketplace_core.orders.
-- The application must validate them.
-- =====================================================================

-- OPTIONAL: uncomment to wipe an old schema (this deletes ALL its data).
-- DROP DATABASE IF EXISTS marketplace_sensitive;

CREATE DATABASE IF NOT EXISTS marketplace_sensitive
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE marketplace_sensitive;

-- ---------------------------------------------------------------------
-- credentials
-- user_id: logical FK -> users.id (RDS #1)
-- Store only a hash (bcrypt / werkzeug), never the plain password.
-- ---------------------------------------------------------------------
CREATE TABLE credentials (
  user_id         INT          NOT NULL PRIMARY KEY,
  password_hash   VARCHAR(255) NOT NULL,
  failed_attempts INT          NOT NULL DEFAULT 0,
  last_login      DATETIME     NULL
  locked_until    DATETIME     NULL DEFAULT NULL AFTER failed_attempts;
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- cards
-- user_id: logical FK -> users.id (RDS #1)
-- NEVER store the full card number or the CVV.
-- Only the payment gateway token and the last 4 digits are kept.
-- ---------------------------------------------------------------------
CREATE TABLE cards (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  user_id       INT          NOT NULL,
  holder_name   VARCHAR(60)  NOT NULL,
  last4         CHAR(4)      NOT NULL,
  brand         VARCHAR(20),
  gateway_token VARCHAR(255) NOT NULL,
  expiry        CHAR(5)      NOT NULL COMMENT 'MM/YY',
  is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
  INDEX idx_cards_user (user_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- payments
-- order_id: logical FK -> orders.id (RDS #1)
-- card_id:  real FK (same database); NULL for payments without a card.
-- ---------------------------------------------------------------------
CREATE TABLE payments (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  order_id          INT           NOT NULL,
  card_id           INT           NULL,
  method            VARCHAR(30)   NOT NULL,
  amount            DECIMAL(10,2) NOT NULL,
  status            ENUM('pending', 'approved', 'rejected', 'refunded')
                    NOT NULL DEFAULT 'pending',
  gateway_reference VARCHAR(100),
  paid_at           DATETIME      NULL,
  CONSTRAINT fk_payments_card FOREIGN KEY (card_id) REFERENCES cards(id),
  CONSTRAINT chk_payments_amount CHECK (amount >= 0),
  INDEX idx_payments_order (order_id)
) ENGINE=InnoDB;
