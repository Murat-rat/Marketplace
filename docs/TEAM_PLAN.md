# Team plan: remaining features

Four packages, one per team member. The project owner **integrates**: reviews each
pull request, runs its SQL, adds its `deploy.env` lines, deploys and merges.

Read [CLAUDE.md](../CLAUDE.md) first (architecture, security rules, how to add a
Lambda). This file says **what** each package must build; `CLAUDE.md` says **how**.

| Package | Owner | Branch | Migration | Lambdas |
|---|---|---|---|---|
| A. Account + My orders | ______ | `account` | `004_...sql` | `account`, `orders` |
| B. Checkout + mock payment | Roberto | `checkout` | `005_...sql` | `checkout` |
| C. Seller products + photos | ______ | `seller-products` | `006_...sql` | `seller` |
| D. Seller sales + reviews | ______ | `sales-reviews` | `007_...sql` | `sales`, `reviews` |

Everyone can start **now**: tests use fake databases, so nobody waits for anyone to
write code. Only the live deployment has an order: **A and C → B → D** (checkout needs
addresses and cards; sales need real orders; reviews need delivered orders).

---

## What already exists (do not rebuild)

| Piece | Where |
|---|---|
| Login/register, JWT (`require_auth(event, seller=True)` for seller routes) | `backend/lambdas/auth`, `common/auth_jwt.py` |
| Catalog: `GET /categories`, `GET /products`, `GET /products/{id}` | `backend/lambdas/catalog` |
| Cart: `GET /cart`, `POST /cart/items`, `PATCH`/`DELETE /cart/items/{product_id}` | `backend/lambdas/cart` (DynamoDB `t_shopping_cart`) |
| Stored procedures `sp_place_order`, `sp_cancel_order`, `sp_update_shipment_status` | `backend/sql/migrations/002_stored_procedures.sql` (read its header: inputs, outputs, error codes) |
| Private image bucket + pre-signed GET links | `common/s3_urls.py`, `backend/images/upload_images.py` |
| Helpers | `common/http.py` (`make_handler`, `parse_body`, `parse_query`, `query_int`), `common/validation.py`, `common/errors.py`, `common/db.py` (`transaction("CORE"/"SECURE")`) |
| Desktop | `desktop/api_client.py`, `ui/workers.py` (`run_in_background`), `ui/widgets.py`, `ui/theme.py`, `ui/format.py` |
| Test patterns | `tests/test_catalog_lambda.py` (fake MySQL), `tests/test_cart_lambda.py` (`FakeTable` for DynamoDB), `tests/test_desktop.py` (screens) |

DB users already created (see `backend/sql/db_users_*.sql`): `app_account`, `app_account_s`,
`app_checkout`, `app_checkout_s`, `app_orders`, `app_orders_s`, `app_seller`, `app_reviews`.
If yours lacks a permission, grant it in **your** migration (and copy the grant into
`db_users_*.sql`), only the exact table/columns needed.

---

## Package A: Account + My orders

### A1. Account (Lambda `account`, env prefixes `ACCOUNT_CORE` / `ACCOUNT_SECURE`)

| Route | Does |
|---|---|
| `GET /account` | Own profile: name, email, phone, seller store (if any) |
| `PATCH /account` | Change `name`, `phone` only (email and role never) |
| `GET /account/addresses` | Own addresses |
| `POST /account/addresses` | `label`?, `address_line`, `city`, `postal_code`, `is_default`? (max **10** per user) |
| `PATCH /account/addresses/{id}` | Edit own address |
| `DELETE /account/addresses/{id}` | Delete own address |
| `GET /account/cards` | Own **active** cards: id, holder_name, brand, last4, expiry (never the token) |
| `POST /account/cards` | `holder_name`, `number`, `expiry` (MM/YY), `cvv` → tokenised by the mock gateway (max **5** active) |
| `DELETE /account/cards/{id}` | Sets `is_active = FALSE` (never deletes: payments reference cards) |

Tables: `users`, `sellers` (RDS #1); `addresses` (RDS #1); `cards` (RDS #2).

**Mock gateway** (you create `backend/layer/python/common/mock_gateway.py`; Roberto adds
`charge` to it later):
```python
def tokenize_card(number: str, expiry: str, cvv: str) -> dict:
    """Validates and 'tokenises' a card. Returns {"token", "last4", "brand"}.
    Raises ValidationError on bad input."""
```
- Number: 13–19 digits, **Luhn check**. Brand from prefix (4 Visa, 51–55 Mastercard,
  34/37 Amex, else "Card"). Expiry MM/YY not in the past. CVV 3–4 digits.
- Token: `"tok_" + secrets.token_hex(16)`.
- **The full number and the CVV are never stored, logged, or returned.** Only token,
  last4, brand, holder, expiry go to `cards`.

Security:
- Every query filters by the JWT user (`WHERE id = %s AND user_id = %s`). Someone
  else's address/card answers **404**, the same as a missing one.
- Only one default address: setting `is_default` clears the others in the same transaction.
- Migration 004: `app_account` needs `SELECT (id, name, email, phone)` and
  `UPDATE (name, phone)` on `users`, and `SELECT (user_id, store_name)` on `sellers`.

### A2. My orders (Lambda `orders`, env prefixes `ORDERS_CORE` / `ORDERS_SECURE`)

| Route | Does |
|---|---|
| `GET /orders?page=` | Own orders, newest first: id, created_at, total, status, item count |
| `GET /orders/{id}` | Own order: items (name, qty, unit_price, status, image), shipments (status, carrier, tracking), payment status |
| `POST /orders/{id}/cancel` | `CALL sp_cancel_order(id, user, @was_paid)`; if `@was_paid`, set that order's `approved` payment to `refunded` |

- Map procedure errors (MySQL 1644): `ORDER_NOT_FOUND` → 404, `ORDER_NOT_CANCELLABLE` → 409.
- Migration 004: `GRANT UPDATE (status) ON marketplace_sensitive.payments TO app_orders_s`
  (for the refund). Update only `WHERE order_id = %s AND status = 'approved'`.

### A screens
- **Account** (top-bar button "My account"): profile, address list with add/edit/delete,
  card list with add/remove. Card form: never keep the number/CVV in memory longer than
  the request; clear the fields after sending; mask the number input.
- **My orders** (top-bar button "My orders"): list → detail with items, shipment status,
  "Cancel order" button only when status is `pending`/`paid` and nothing has shipped.

### A tests (minimum)
- 401 without token on every route; 400 on bad input and unknown fields.
- Other user's address / card / order → 404 (and nothing changed).
- Card: Luhn failure, expired, bad CVV rejected; stored row has only token + last4 (assert
  the full number appears nowhere in the DB call arguments or the response).
- Limits (10 addresses, 5 cards). Cancel maps both error codes; refund only when paid.

---

## Package B: Checkout + mock payment (Roberto)

Lambda `checkout`, env prefixes `CHECKOUT_CORE` / `CHECKOUT_SECURE`, plus `CART_TABLE_NAME`.

| Route | Does |
|---|---|
| `POST /checkout` | Body `{address_id, card_id}`. Buys **everything in the caller's cart** |

Flow (the cart, prices and totals all come from the server, never from the body):
1. Read the caller's cart from DynamoDB (same table/keys as the cart Lambda). Empty → 400.
2. RDS #2: the card must belong to the caller and be active (`app_checkout_s`), else 404.
3. RDS #1: `CALL sp_place_order(user, address_id, items_json, @order_id, @total)`.
   Map errors: `ADDRESS_NOT_FOUND` → 404; `INVALID_ITEMS` → 400;
   `OUT_OF_STOCK`, `PRODUCT_UNAVAILABLE`, `OWN_PRODUCT`, `TOTAL_TOO_LARGE` → 409.
4. RDS #2: `INSERT payments (order_id, card_id, method='card', amount=@total, status='pending')`.
5. `mock_gateway.charge(card_last4, amount)` (you add it to A's module):
   approved unless `last4 == "0002"` (declined); returns a reference like `"pay_" + hex`.
6. **Approved**: payment → `approved` + `gateway_reference` + `paid_at`;
   `UPDATE orders SET status='paid' WHERE id=%s AND status='pending'`;
   `UPDATE order_items SET status='confirmed' WHERE order_id=%s AND status='pending'`;
   delete the bought lines from the cart. Return 201 `{order_id, total, status:"paid"}`.
7. **Declined**: payment → `rejected`; `CALL sp_cancel_order(order_id, user, @x)` (stock goes
   back); raise `PaymentDeclined` (define it in the handler:
   `class PaymentDeclined(AppError): status = 402; code = "payment_declined"`). The cart is kept.
8. **Any error after step 3**: call `sp_cancel_order` so stock is never left reserved.

Security / correctness:
- Add `"POST /checkout": {"ThrottlingRateLimit": 1, "ThrottlingBurstLimit": 3}` to
  `ROUTE_THROTTLE` in `deploy.py`.
- Double clicks: the desktop disables the button while the request runs.
- Never log card data or the token. The response never includes the token.

Screen: **Checkout** page opened from the cart ("Proceed to checkout"): order summary
(from `GET /cart`), choose address (`GET /account/addresses`) and card
(`GET /account/cards`), "Pay" button, then a success page with the order number or the
decline message. Until package A is merged, use a fake API in tests (see `tests/test_desktop.py`).

Tests: empty cart; foreign card/address → 404; each procedure error mapping; declined card
(last4 0002) → 402 and `sp_cancel_order` called; approved → order paid, items confirmed,
cart lines removed; failure after the order is created → `sp_cancel_order` called; total in
the payment equals `@total` (not anything from the request).

---

## Package C: Seller products + photos

Lambda `seller`, env prefix `SELLER_CORE`, plus `IMAGES_BUCKET`. All routes use
`require_auth(event, seller=True)` and filter by `principal.seller_id`.

| Route | Does |
|---|---|
| `GET /seller/products?page=&q=` | Own products, **including** inactive and out-of-stock |
| `POST /seller/products` | `category_id`, `name`, `description`?, `price`, `stock` |
| `PATCH /seller/products/{id}` | Any of: `category_id`, `name`, `description`, `price`, `stock`, `is_active` |
| `POST /seller/products/{id}/images/upload-url` | Body `{content_type}` (jpeg/png/webp). Returns a **pre-signed POST** for a server-chosen key `products/{id}/{uuid}.{ext}` |
| `POST /seller/products/{id}/images` | Body `{key}`: confirms the upload, then inserts into `product_images` |
| `DELETE /seller/products/{id}/images/{image_id}` | Removes the row (and the S3 object) |
| `PATCH /seller/products/{id}/images/{image_id}` | `{is_primary: true}` (only one primary) |

Rules:
- Stock: integer 0–100000, set by the seller (availability is `stock > 0`, never a flag).
  Price: `validation.money`. Category must exist, be active, and be a **subcategory**.
- Seller can never change `average_rating`, `review_count`, `seller_id`, `published_at`.
  Migration 006: replace `app_seller`'s table-wide `UPDATE` on `products` with
  `UPDATE (category_id, name, description, price, stock, is_active)`.
- Images, max **5** per product:
  - Pre-signed POST with conditions: exact `key`, `Content-Type`, `content-length-range`
    1 B – 5 MB, expires in 5 min.
  - Confirm route: the key must start with `products/{that product id}/` and the product
    must be the caller's; read the first 16 bytes (ranged GET) and check the magic bytes
    like `backend/images/upload_images.py` does. If wrong, delete the object and return 400.
- Desktop uploads straight to S3 with the pre-signed POST, **without** the JWT.

Screens: **My products** (top-bar button "My store", visible only for sellers): table of own
products with stock and active state, "New product" and "Edit"; **Product form** with
category picker (subcategories only), price, stock, description, photo list (add, remove,
make primary).

Tests: non-seller → 403; another seller's product → 404 on every route; forbidden fields
(`average_rating`, `seller_id`) → 400; stock/price limits; image key for another product → 400;
fake image content → 400 and object deleted; 6th image → 409.

---

## Package D: Seller sales + reviews

### D1. Sales (Lambda `sales`, env prefixes `SALES_CORE` / `SALES_SECURE`)

Migration 007 creates **new** users (one DB user per Lambda):
- `app_sales` on RDS #1: `SELECT` on `orders`, `order_items`, `shipments`, `products`,
  `EXECUTE ON PROCEDURE sp_update_shipment_status`; and revokes from `app_seller` what it
  no longer needs (`SELECT` on `orders`, `order_items`, `shipments`, `EXECUTE` on the procedure).
- `app_sales_s` on RDS #2: `SELECT (id, order_id, status)` and `UPDATE (status)` on `payments`.

| Route | Does |
|---|---|
| `GET /sales?status=&page=` | Shipments containing **only the caller's** items: order date, items, buyer's shipping address, shipment status |
| `POST /sales/shipments/{id}/status` | `{status, carrier?, tracking?}` → `CALL sp_update_shipment_status(seller_id, id, ...)`; if it returns order status `cancelled`, mark the order's `approved` payment `refunded` |

- Map errors: `SHIPMENT_NOT_FOUND` → 404; `ORDER_NOT_PAID`, `INVALID_TRANSITION` → 409;
  `INVALID_STATUS`, `CARRIER_REQUIRED` → 400; `SELLER_INACTIVE` → 403.
- Never show the buyer's email/phone; only the shipping address copied into the order.

### D2. Reviews (Lambda `reviews`, env prefix `REVIEWS_CORE`, plus `REVIEWS_TABLE_NAME=t_review`)

DynamoDB `t_review`: PK `product_id` (Number), SK `review_id` (String), `user_id`, `rating`,
`comment`, `publication_date` (ISO string). **`review_id = str(user_id)`**, so each user has at
most one review per product and editing is a simple overwrite.

| Route | Does |
|---|---|
| `GET /products/{id}/reviews?page=` | Reviews of a product: rating, comment, date, author first name, `is_mine` |
| `PUT /products/{id}/review` | `{rating: 1-5, comment?: ≤1000 chars}`; create or edit own |
| `DELETE /products/{id}/review` | Delete own |

- Allowed only if the caller has an `order_items` row for that product with
  `status = 'delivered'` in one of **their** orders (else 403).
- After a change, recompute from all of the product's reviews and
  `UPDATE products SET average_rating = %s, review_count = %s WHERE id = %s`.
- Never return other users' `user_id`; show only the first name
  (migration 007: `GRANT SELECT (id, name) ON users TO app_reviews`).

### D screens
- **Sales** (top-bar button "My sales", sellers only): shipments to prepare/ship, with
  buttons for the allowed next status and a carrier/tracking form for "shipped".
- **Reviews** section on the product detail page: list + "Write/Edit your review" (only
  shown when allowed; the server decides anyway). Comments shown as **plain text**.

### D tests
Other seller's shipment → 404; every error-code mapping; refund only when the order became
`cancelled`; review without a delivered purchase → 403; second review edits (one row);
rating 0/6/"5" → 400; average/count recomputed; other users' ids never in responses.

---

## Team rules

1. **Branch** from an up-to-date `main` (`git switch main`, `git pull`,
   `git switch -c <branch>`). Before the pull request: `git merge main`, run the tests, push.
2. **Shared files** (`deploy.py`, `api_client.py`, `shell_view.py`, `db_users_*.sql`,
   `deploy.env.example`, `CLAUDE.md`): **only add** your part (new entry, new method, new
   button/page) next to the existing ones. Never reorganise or rename what is there.
3. **One migration file per package** with your number. Every new DB user uses password
   `CHANGE_ME`; the owner sets the real one when running it.
4. **Never** run AWS commands, `deploy.py` or SQL on the real databases, and never ask for
   credentials. To try your screens against the real API, use the URL in `desktop/.env`
   once the owner has deployed your Lambda.
5. `.venv\Scripts\python -m pytest -q` must pass before opening the pull request.
6. Fill in the pull request template (SQL to run, `deploy.env` lines, routes).
