## Package
<!-- A (account + orders) / B (checkout) / C (seller products) / D (sales + reviews) -->

## What this adds
<!-- Short list of features and screens. -->

## For the owner: deployment steps
**SQL to run** (file + which RDS, or "none"):
-

**`deploy.env` lines to add** (names only, never real values):
-

**Lambdas / routes** (deploy with `deploy.py --only <name>`):
-

## Checklist
- [ ] Branched from an up-to-date `main`, and merged `main` again before opening this PR
- [ ] `.venv\Scripts\python -m pytest -q` passes
- [ ] Tests cover: no token (401), bad input / unknown fields (400), other users' data (404/403)
- [ ] User identity comes only from the JWT; every query on user data filters by it
- [ ] Prices/totals come from the database, never from the request
- [ ] SQL is parameterised (`%s` only); stored procedures used for orders/stock/shipments
- [ ] No secrets, `.env` files, real passwords, card numbers or tokens in the code or logs
- [ ] New DB users have only the exact tables/columns needed, password `CHANGE_ME`
- [ ] Shared files (`deploy.py`, `api_client.py`, `shell_view.py`, `db_users_*.sql`): only additions
- [ ] User/seller text shown as plain text in the desktop app
