# Marketplace project: rules for AI agents and contributors

Python desktop marketplace (PySide6) backed by AWS Lambdas, two MySQL RDS databases
and DynamoDB. A teacher will actively look for vulnerabilities, so **security comes
first**. Read this whole file before changing anything.

## Architecture

```
desktop/ (PySide6)  --HTTPS + JWT-->  API Gateway HTTP API  -->  Lambdas (Python 3.12, in the VPC)
                                                                  |-- RDS #1 marketplace_core      (MySQL)
                                                                  |-- RDS #2 marketplace_sensitive (MySQL)
                                                                  |-- DynamoDB t_shopping_cart, t_review
                                                                  '-- S3 (product images)
```

- The desktop app **never** talks to a database or to AWS directly. Only to the API.
- Schemas: `backend/sql/schema_core.sql`, `backend/sql/schema_sensitive.sql`, `ERD Diagram.xml`.
  Use the real ENUM values from the schema files; do not invent new ones.
- A "seller" is a user with `role = 'buyer'` plus an active row in `sellers` (role is only `buyer`/`admin`).
- Stock is set by the seller; availability is always `stock > 0` (never a flag).
  Purchases decrement stock atomically (`UPDATE ... SET stock = stock - %s WHERE id = %s AND stock >= %s`).
- A user may review a product once (and edit it) only after a **delivered** order containing it.

## Where things live

| Path | What |
|---|---|
| `backend/layer/python/common/` | Shared helpers: `db`, `auth_jwt`, `http`, `validation`, `errors`, `passwords`, `s3_urls` |
| `backend/lambdas/<name>/handler.py` | Routes + input validation for one Lambda |
| `backend/lambdas/<name>/repository.py` | All SQL for that Lambda (parameterised only) |
| `backend/deploy.py` | Builds the layer and deploys every Lambda and route in `FUNCTIONS` |
| `backend/sql/migrations/` | Numbered SQL changes (`002_...sql`), run by the project owner |
| `desktop/api_client.py` | The only place the desktop makes HTTP calls |
| `desktop/ui/views/` | Screens |
| `tests/` | pytest; must pass with no AWS access |

## Adding a feature (e.g. the cart)

1. Create `backend/lambdas/<name>/handler.py` + `repository.py`, following `catalog/` as the model:
   `make_handler(routes)`, `require_auth(event)`, `parse_body`/`parse_query` with an explicit
   allow-list, `validation.*` for every field, errors from `common.errors`.
2. Add an entry to `FUNCTIONS` in `backend/deploy.py` (routes, `core`/`secure` env prefix, memory, timeout).
3. If it needs DB access, add a **new least-privilege MySQL user** for it in
   `backend/sql/db_users_core.sql` / `db_users_sensitive.sql` (password `CHANGE_ME`), granting
   only the tables/columns it uses, and add `<PREFIX>_CORE_DB_USER/PASSWORD` placeholders to
   `backend/deploy.env.example`. Table changes go in a new numbered migration file.
4. Add API methods to `desktop/api_client.py` and the screen under `desktop/ui/views/`.
5. Write tests (see `tests/test_catalog_lambda.py` and `tests/test_desktop.py`): fake the DB,
   cover auth (401/403), bad input (400), and other users' data (must be 404/403).
6. Run `.venv\Scripts\python -m pytest -q`. Everything must pass.
7. Open a pull request. **Only the project owner deploys and runs SQL.**

## Security rules (non-negotiable)

- **No secrets in the repo.** Never commit `.env` files, `deploy.env`, AWS credentials,
  DB passwords, JWT secrets or tokens. Real passwords go only in git-ignored files
  (`backend/deploy.env`, `backend/sql/local/`). Placeholders are `CHANGE_ME`.
- **Never run AWS commands, `deploy.py`, or SQL against the real databases.** You have no
  credentials and must not ask for them.
- SQL: parameterised queries only (`%s`). Never build SQL from user input; for ORDER BY or
  column names use a fixed whitelist dict.
- Identity comes **only** from the JWT (`require_auth`), never from a `user_id` in the body or
  query. Every query on user-owned data filters by the caller's id (no IDOR).
- Prices and totals are always computed on the server from the DB, never trusted from the client.
- Validate every input with `common.validation`; reject unknown fields.
- Errors: return generic messages; never return stack traces, SQL or internal ids of other users.
  Never log request bodies, passwords, card data or tokens.
- Card data: the app stores only what the schema allows (never the full number or CVV);
  the payment gateway is a mock.
- Passwords are hashed with `common.passwords` (scrypt). Do not add another scheme.
- Desktop: show user/seller-provided text as plain text (`Qt.TextFormat.PlainText`), never HTML.
  Only HTTPS URLs. Never send the JWT anywhere except the API.
- Do not add new dependencies without a good reason; pin exact versions.

## Code style

- Python 3.12, type hints where helpful, small functions, English names and comments.
- Keep handlers thin: validation and HTTP in `handler.py`, SQL in `repository.py`.
- Run the desktop app with `.venv\Scripts\python desktop\main.py`.
