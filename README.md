# Marketplace

Desktop marketplace app (Python + PySide6) with an AWS backend: API Gateway, Python
Lambdas, two MySQL RDS databases and DynamoDB.

## Try the desktop app offline

For a UI demo without AWS or database access, set `LOCAL_DEMO=1` in `desktop/.env`
and run `python desktop/main.py`. This mode uses sample products and an in-memory
cart; nothing is sent to the API or saved, and the demo data is cleared when the
app closes. Remove or set `LOCAL_DEMO=0` to use the connected API configuration.

## For team members

You do **not** need AWS access. You write code and tests; the project owner reviews,
runs any SQL and deploys.

### 1. Set up (once)

```powershell
git clone <repo-url>
cd <repo-folder>
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt -r desktop\requirements.txt
copy desktop\.env.example desktop\.env
```

Put the API URL the owner gives you in `desktop\.env` as `API_URL=...`.

### 2. Run

```powershell
.venv\Scripts\python desktop\main.py
.venv\Scripts\python -m pytest -q
```

Register your own account in the app to try it.

### 3. Work on a feature

```powershell
git checkout -b feature/cart
# ...make changes, run the tests...
git add -A
git commit -m "Add shopping cart"
git push -u origin feature/cart
```

Then open a pull request on GitHub. Mention in it any SQL that must be run
(new migration files or MySQL users) so the owner can run it before deploying.

### Rules

Read [CLAUDE.md](CLAUDE.md) before starting (AI agents read it automatically). The short version:

- Never commit secrets (`.env`, passwords, keys, tokens). Use `CHANGE_ME` placeholders.
- Never run AWS commands, `deploy.py` or SQL against the real databases.
- Tests must pass before opening a pull request.

## For the owner

Infrastructure and deployment: [docs/SETUP.md](docs/SETUP.md).
