# AWS setup (Learner Lab)

The desktop app talks only to API Gateway over HTTPS. The Lambdas are the only
thing that can reach the databases.

```
Desktop app ──HTTPS + JWT──► API Gateway ──► Lambdas (in the VPC, LabRole)
                                                ├──► RDS #1 core     (private)
                                                ├──► RDS #2 secure   (private)
                                                ├──► DynamoDB  (gateway endpoint)
                                                └──► S3        (gateway endpoint)
```

## 1. Network

1. **VPC and subnets.** Use the VPC that holds your RDS instances. Note two subnet
   IDs in different Availability Zones; they go in `SUBNET_IDS`.
2. **Lambda security group** (e.g. `marketplace-lambda-sg`):
   - Inbound: none.
   - Outbound: allow all (the default).
   - Put its ID in `LAMBDA_SECURITY_GROUP_ID`.
3. **RDS security groups.** On *each* RDS instance's security group:
   - Inbound: MySQL/Aurora (3306) with source = `marketplace-lambda-sg`.
   - Add your own public IP on 3306 **only while you run the SQL scripts**, then remove it.
4. **RDS "Publicly accessible" = No** on both instances
   (RDS → Modify → Connectivity). If you need to run SQL from your PC, switch
   it on temporarily, together with step 3's temporary rule, and switch it off afterwards.
5. **VPC gateway endpoints** (VPC → Endpoints → Create endpoint; both are free):
   - `com.amazonaws.<region>.dynamodb`, type Gateway, select the route tables of the Lambda subnets.
   - `com.amazonaws.<region>.s3`, type Gateway, same route tables.

   Without these, Lambdas inside the VPC cannot reach DynamoDB or S3 (there is no NAT gateway).

## 2. Database users

Run as the RDS master user (MySQL Workbench or the `mysql` CLI):

1. Copy `backend/sql/db_users_core.sql` and `backend/sql/db_users_sensitive.sql`
   into `backend/sql/local/` (git-ignored) and replace every `CHANGE_ME` there with
   a strong, unique password. **Never put real passwords in the tracked copies.**
2. Run the core one on **RDS #1** and the sensitive one on **RDS #2**.
3. Run the files in `backend/sql/migrations/` in order, then `backend/sql/seed/seed_catalog.sql` on RDS #1.
4. Copy the passwords you chose into `backend/deploy.env`.

The master user is **never** given to the Lambdas.

## 3. Shopping cart

The cart Lambda uses the existing DynamoDB table `t_shopping_cart`; it does not
create or migrate the table. Confirm it has a numeric partition key `user_id`, a
numeric sort key `product_id`, numeric `quantity`, and numeric `expiration` with
TTL enabled on `expiration`. Set `CART_TABLE_NAME` in `backend/deploy.env` if the
table has a different name.

The Lambda execution role must be allowed `dynamodb:Query`, `dynamodb:GetItem`,
`dynamodb:UpdateItem`, and `dynamodb:DeleteItem` on this table. The Lambda subnets
also need the DynamoDB gateway endpoint described in Network.

## 4. Deploy

1. In the Learner Lab, open **AWS Details**, copy the credentials into
   `%USERPROFILE%\.aws\credentials` under `[default]`. They change every time
   you start the Lab.
2. Install the tools once:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements-dev.txt
   ```

3. Copy `backend/deploy.env.example` to `backend/deploy.env` and fill it in.
4. Deploy:

   ```powershell
   python backend/deploy.py
   ```

   The script prints the API URL at the end.

## 5. Quick test

```powershell
$api = "https://xxxx.execute-api.us-east-1.amazonaws.com"
Invoke-RestMethod -Method Post -Uri "$api/register" -ContentType "application/json" -Body '{"name":"Ana Test","email":"ana@test.com","phone":"5512345678","password":"Secreta123","account_type":"buyer"}'
Invoke-RestMethod -Method Post -Uri "$api/login" -ContentType "application/json" -Body '{"email":"ana@test.com","password":"Secreta123"}'
```

## Known limitation: one IAM role

The Learner Lab does not allow custom IAM roles, so every Lambda runs with
`LabRole`. To compensate, each Lambda gets its own MySQL user with only the
tables and columns it needs (see `backend/sql/`), and Lambdas that do not need
sensitive data receive no credentials for RDS #2 at all. In a real AWS
account, each Lambda would also get its own IAM role.
