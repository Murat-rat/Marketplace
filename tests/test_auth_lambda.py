"""auth Lambda tests with an in-memory fake of both databases."""

import datetime as dt
import importlib.util
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

AUTH_DIR = Path(__file__).resolve().parents[1] / "backend" / "lambdas" / "auth"


class FakeConn:
    def __init__(self, db):
        self.db = db

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()


class FakeDB:
    """A tiny transactional store: changes are staged until commit()."""

    def __init__(self):
        self.data = {"users": {}, "sellers": {}, "credentials": {}}
        self.staged = None
        self.next_id = {"users": 1, "sellers": 1}

    def begin(self):
        if self.staged is None:
            self.staged = json.loads(json.dumps(self.data))

    def commit(self):
        if self.staged is not None:
            self.data = self.staged
            self.staged = None

    def rollback(self):
        self.staged = None

    @property
    def view(self):
        self.begin()
        return self.staged


@pytest.fixture
def auth(monkeypatch):
    sys.path.insert(0, str(AUTH_DIR))
    sys.modules.pop("repository", None)
    spec = importlib.util.spec_from_file_location("auth_handler", AUTH_DIR / "handler.py")
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    sys.path.remove(str(AUTH_DIR))

    dbs = {"CORE": FakeDB(), "SECURE": FakeDB()}

    @contextmanager
    def transaction(prefix):
        db = dbs[prefix]
        db.begin()
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise

    @contextmanager
    def open_transaction(prefix):
        db = dbs[prefix]
        db.begin()
        try:
            yield FakeConn(db), db
        finally:
            db.rollback()

    monkeypatch.setattr(handler.db, "transaction", transaction)
    monkeypatch.setattr(handler.db, "open_transaction", open_transaction)

    repo = handler.repo

    def find_user_by_email(cur, email):
        return next((dict(u) for u in cur.view["users"].values() if u["email"] == email), None)

    def insert_user(cur, *, name, email, phone, role, created_at):
        uid = cur.next_id["users"]
        cur.next_id["users"] += 1
        cur.view["users"][str(uid)] = {"id": uid, "name": name, "email": email, "phone": phone,
                                       "role": role, "is_active": True}
        return uid

    def insert_seller(cur, *, user_id, store_name, description, created_at):
        sid = cur.next_id["sellers"]
        cur.next_id["sellers"] += 1
        cur.view["sellers"][str(sid)] = {"id": sid, "user_id": user_id, "store_name": store_name}
        return sid

    def find_active_seller_id(cur, user_id):
        return next((s["id"] for s in cur.view["sellers"].values() if s["user_id"] == user_id), None)

    def insert_credentials(cur, *, user_id, password_hash):
        cur.view["credentials"][str(user_id)] = {"password_hash": password_hash, "failed_attempts": 0,
                                                 "locked_until": None}

    def delete_credentials(cur, user_id):
        cur.view["credentials"].pop(str(user_id), None)

    # The fake store is JSON-copied between transactions, so datetimes are kept as ISO strings.
    def get_credentials(cur, user_id):
        c = cur.view["credentials"].get(str(user_id))
        if not c:
            return None
        c = dict(c)
        c["locked_until"] = dt.datetime.fromisoformat(c["locked_until"]) if c["locked_until"] else None
        return c

    def register_failed_attempt(cur, user_id, *, max_attempts, lock_until):
        c = cur.view["credentials"][str(user_id)]
        if c["failed_attempts"] + 1 >= max_attempts:
            c["locked_until"] = lock_until.isoformat()
            c["failed_attempts"] = 0
        else:
            c["failed_attempts"] += 1

    def register_successful_login(cur, user_id, now):
        c = cur.view["credentials"][str(user_id)]
        c["failed_attempts"] = 0
        c["locked_until"] = None

    for fn in (find_user_by_email, insert_user, insert_seller, find_active_seller_id, insert_credentials,
               delete_credentials, get_credentials, register_failed_attempt, register_successful_login):
        monkeypatch.setattr(repo, fn.__name__, fn)

    handler.dbs = dbs
    return handler


def call(handler, route, body):
    resp = handler.lambda_handler({"routeKey": route, "body": json.dumps(body)}, None)
    return resp["statusCode"], json.loads(resp["body"])


SHOPPER = {"name": "Ana Test", "email": "ana@test.com", "phone": "55 1234 5678",
           "password": "Secreta123", "account_type": "buyer"}


def test_register_and_login(auth):
    status, body = call(auth, "POST /register", SHOPPER)
    assert status == 201 and body["token"] and body["user"]["role"] == "buyer"
    assert body["user"]["seller_id"] is None
    assert auth.dbs["CORE"].data["users"]["1"]["phone"] == "5512345678"
    stored = auth.dbs["SECURE"].data["credentials"]["1"]["password_hash"]
    assert "Secreta123" not in stored

    status, body = call(auth, "POST /login", {"email": "ANA@test.com", "password": "Secreta123"})
    assert status == 200 and body["user"]["id"] == 1


def test_register_seller_is_buyer_with_seller_profile(auth):
    status, body = call(auth, "POST /register", {**SHOPPER, "account_type": "seller", "store_name": "Ana's Shop"})
    assert status == 201 and body["user"]["seller_id"] == 1
    assert auth.dbs["CORE"].data["users"]["1"]["role"] == "buyer"
    status, body = call(auth, "POST /login", {"email": "ana@test.com", "password": "Secreta123"})
    assert body["user"]["seller_id"] == 1


def test_seller_requires_store_name(auth):
    status, body = call(auth, "POST /register", {**SHOPPER, "account_type": "seller"})
    assert status == 400 and body["field"] == "store_name"


def test_phone_is_optional(auth):
    body = {k: v for k, v in SHOPPER.items() if k != "phone"}
    assert call(auth, "POST /register", body)[0] == 201


@pytest.mark.parametrize("extra", [{"role": "admin"}, {"account_type": "admin"}, {"is_active": False},
                                   {"user_id": 99}])
def test_register_blocks_privilege_fields(auth, extra):
    status, _ = call(auth, "POST /register", {**SHOPPER, **extra})
    assert status == 400
    assert auth.dbs["CORE"].data["users"] == {}


def test_duplicate_email(auth):
    call(auth, "POST /register", SHOPPER)
    status, body = call(auth, "POST /register", SHOPPER)
    assert status == 409


def test_secure_db_failure_rolls_back_core(auth, monkeypatch):
    def broken(cur, **kwargs):
        raise RuntimeError("RDS #2 unavailable")

    monkeypatch.setattr(auth.repo, "insert_credentials", broken)
    status, _ = call(auth, "POST /register", SHOPPER)
    assert status == 500
    assert auth.dbs["CORE"].data["users"] == {}  # no user without a password


def test_login_failures_look_identical(auth):
    call(auth, "POST /register", SHOPPER)
    unknown = call(auth, "POST /login", {"email": "nobody@test.com", "password": "Secreta123"})
    wrong = call(auth, "POST /login", {"email": "ana@test.com", "password": "Wrong1234"})
    bad_format = call(auth, "POST /login", {"email": "x", "password": ""})
    assert unknown == wrong == bad_format
    assert unknown[0] == 401


def test_lockout_after_max_attempts_then_unlocks(auth, monkeypatch):
    call(auth, "POST /register", SHOPPER)
    for _ in range(auth.MAX_FAILED_ATTEMPTS):
        assert call(auth, "POST /login", {"email": "ana@test.com", "password": "Wrong1234"})[0] == 401
    cred = auth.dbs["SECURE"].data["credentials"]["1"]
    assert cred["locked_until"] is not None and cred["failed_attempts"] == 0

    # While locked, even the right password is refused, and guesses are not counted.
    assert call(auth, "POST /login", {"email": "ana@test.com", "password": "Secreta123"})[0] == 401

    # After the lock window passes, the right password works again.
    real_now = auth._now
    monkeypatch.setattr(auth, "_now", lambda: real_now() + dt.timedelta(minutes=auth.LOCK_MINUTES + 1))
    assert call(auth, "POST /login", {"email": "ana@test.com", "password": "Secreta123"})[0] == 200
    assert auth.dbs["SECURE"].data["credentials"]["1"]["locked_until"] is None


def test_success_resets_counter(auth):
    call(auth, "POST /register", SHOPPER)
    call(auth, "POST /login", {"email": "ana@test.com", "password": "Wrong1234"})
    call(auth, "POST /login", {"email": "ana@test.com", "password": "Secreta123"})
    assert auth.dbs["SECURE"].data["credentials"]["1"]["failed_attempts"] == 0
