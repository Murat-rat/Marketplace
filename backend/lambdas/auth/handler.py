"""auth Lambda: POST /register and POST /login.

Uses MySQL users app_auth (RDS #1) and app_auth_s (RDS #2).
"""

import datetime as dt
import os

import pymysql

from common import db, passwords, validation
from common.auth_jwt import issue_token
from common.errors import Conflict, Unauthorized, ValidationError
from common.http import make_handler, parse_body

import repository as repo

MAX_FAILED_ATTEMPTS = int(os.environ.get("MAX_FAILED_ATTEMPTS", "5"))
LOCK_MINUTES = int(os.environ.get("LOCK_MINUTES", "15"))
# What the person picks when signing up. In the database everyone gets
# users.role = 'buyer'; a seller is a buyer who ALSO has a row in `sellers`.
# 'admin' can never be obtained through the API.
ACCOUNT_TYPES = {"buyer", "seller"}
DB_ROLE_FOR_NEW_USERS = "buyer"

# One message for every login failure (unknown email, wrong password,
# inactive or locked account) so attackers cannot tell which one happened.
LOGIN_FAILED = "Invalid email or password, or the account is locked."


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _session(user: dict, seller_id: int | None) -> dict:
    token, expires_in = issue_token(user["id"], user["role"], seller_id)
    return {
        "token": token,
        "expires_in": expires_in,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "seller_id": seller_id,
        },
    }


def register(event):
    body = parse_body(event, {"name", "email", "phone", "password", "account_type", "store_name", "store_description"})
    name = validation.string(body, "name", max_len=80, min_len=2)
    email = validation.email(body)
    phone = validation.phone(body, required=False)  # users.phone is nullable
    password = validation.new_password(body)
    account_type = validation.choice(body, "account_type", ACCOUNT_TYPES)
    role = DB_ROLE_FOR_NEW_USERS
    store_name = store_description = None
    if account_type == "seller":
        store_name = validation.string(body, "store_name", max_len=60, min_len=2)
        store_description = validation.string(body, "store_description", max_len=2000, required=False)
    elif "store_name" in body or "store_description" in body:
        raise ValidationError("Only sellers can have a store", "store_name")

    # Hash before opening any transaction (scrypt is deliberately slow).
    password_hash = passwords.hash_password(password)
    now = _now()

    # Cross-database flow: the core transaction stays open until the
    # credentials are safely stored in RDS #2, so a failure on either side
    # never leaves a user without a password (or a password without a user).
    with db.open_transaction(db.CORE) as (core_conn, cur):
        if repo.find_user_by_email(cur, email):
            raise Conflict("An account with this email already exists", "email")
        try:
            user_id = repo.insert_user(cur, name=name, email=email, phone=phone, role=role, created_at=now)
            seller_id = None
            if account_type == "seller":
                seller_id = repo.insert_seller(
                    cur, user_id=user_id, store_name=store_name, description=store_description, created_at=now
                )
        except pymysql.err.IntegrityError:
            # Two registrations with the same email at the same moment: UNIQUE wins.
            raise Conflict("An account with this email already exists", "email") from None

        with db.transaction(db.SECURE) as scur:
            repo.insert_credentials(scur, user_id=user_id, password_hash=password_hash)

        try:
            core_conn.commit()
        except Exception:
            with db.transaction(db.SECURE) as scur:
                repo.delete_credentials(scur, user_id)
            raise

    user = {"id": user_id, "name": name, "email": email, "role": role}
    return 201, _session(user, seller_id)


def login(event):
    body = parse_body(event, {"email", "password"})
    try:
        email = validation.email(body)
        password = validation.any_password(body)
    except ValidationError:
        raise Unauthorized(LOGIN_FAILED) from None

    with db.transaction(db.CORE) as cur:
        user = repo.find_user_by_email(cur, email)
        seller_id = repo.find_active_seller_id(cur, user["id"]) if user else None

    if not user or not user["is_active"]:
        passwords.burn_time(password)
        raise Unauthorized(LOGIN_FAILED)

    ok = False
    now = _now()
    with db.transaction(db.SECURE) as scur:
        cred = repo.get_credentials(scur, user["id"])
        locked = cred is not None and cred["locked_until"] is not None and cred["locked_until"] > now
        if cred is None or locked:
            # While locked, the password is not even checked, so guessing
            # during the lock window gives an attacker nothing.
            passwords.burn_time(password)
        elif passwords.verify_password(password, cred["password_hash"]):
            repo.register_successful_login(scur, user["id"], now)
            ok = True
        else:
            repo.register_failed_attempt(
                scur, user["id"],
                max_attempts=MAX_FAILED_ATTEMPTS,
                lock_until=now + dt.timedelta(minutes=LOCK_MINUTES),
            )
    # Raise only after the transaction committed, so the failed attempt is saved.
    if not ok:
        raise Unauthorized(LOGIN_FAILED)

    return 200, _session(user, seller_id)


lambda_handler = make_handler({
    "POST /register": register,
    "POST /login": login,
})
