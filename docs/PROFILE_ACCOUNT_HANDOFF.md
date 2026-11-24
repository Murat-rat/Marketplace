# Profile and payment preview handoff

## Current behavior

- Clicking the signed-in email in the desktop header opens **Your profile**.
- Email changes call `PATCH /account/email`; the authenticated user's id comes only from the JWT.
- Password changes call `PATCH /account/password`; the current password is verified and the new password is stored as the project's existing scrypt hash.
- The local demo supports the same screens without network access. Its changes are temporary and disappear when the app closes.
- **Payment methods** is a visual-only preview. The sample cards are not real cards, the add button is disabled, and the screen collects no card data.

## Existing database objects used

No tables or columns were added.

| Purpose | Existing database object | Existing fields used |
|---|---|---|
| Account email | RDS #1, `marketplace_core.users` | `id`, `email`, `is_active` |
| Password | RDS #2, `marketplace_sensitive.credentials` | `user_id`, `password_hash`, `failed_attempts`, `locked_until` |
| Future real payment methods | RDS #2, `marketplace_sensitive.cards` | `user_id`, `holder_name`, `last4`, `brand`, `gateway_token`, `expiry`, `is_active` |

The desktop app must continue to call API Gateway only. It must never connect directly to MySQL, DynamoDB, or AWS. The auth Lambda already receives the `AUTH` credentials for both RDS instances, so the profile routes are added to that Lambda rather than creating a new database service.

## Before enabling the new routes on AWS

The project owner must apply these least-privilege grants as the RDS master user. They grant updates only to the existing email and password-hash columns:

```sql
GRANT UPDATE (email)
  ON marketplace_core.users TO 'app_auth'@'%';

GRANT UPDATE (password_hash)
  ON marketplace_sensitive.credentials TO 'app_auth_s'@'%';
```

The same grants are included in `backend/sql/db_users_core.sql` and `backend/sql/db_users_sensitive.sql` for future setup. Do not run SQL or deploy from an AI session; the project owner applies the grants and deploys the auth Lambda/API. The desktop endpoints are already wired to the route names above.

To deploy only the updated auth Lambda and API routes, the owner can use the project's normal deployment workflow with `backend/deploy.py --only auth`, after the AWS environment and grants are ready. The deploy script requires the owner's AWS credentials and is not run as part of local development.

## Security requirements for future changes

- Keep profile identity bound to `require_auth(event)`; ignore any client-supplied `user_id`.
- Keep SQL parameterized and preserve the unique email constraint as the concurrency guard.
- Verify the current password before changing it. Hash new passwords with `common.passwords.hash_password`; never store plaintext.
- Never store full card numbers or CVVs. Real card enrollment requires a payment gateway token and must use the existing token/last-four design, not the mock card values in the desktop preview.
- Do not add schema migrations for this profile feature unless the project owner explicitly approves a schema change.
