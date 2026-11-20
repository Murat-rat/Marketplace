"""Desktop settings, read from desktop/.env (or real environment variables).

The app only needs the public API URL. It never holds database passwords
or AWS keys: everything goes through the API.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

ENV_FILE = Path(__file__).resolve().parent / ".env"


def _load_env_file() -> dict:
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def api_url() -> str:
    url = os.environ.get("API_URL") or _load_env_file().get("API_URL", "")
    url = url.rstrip("/")
    parsed = urlparse(url)
    # Refuse plain HTTP so tokens and passwords are never sent unencrypted.
    # localhost is allowed only for local testing.
    if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1"):
        raise RuntimeError(
            "API_URL is missing or not HTTPS. Set it in desktop/.env, e.g.\n"
            "API_URL=https://xxxx.execute-api.us-east-1.amazonaws.com"
        )
    return url
