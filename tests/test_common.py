import json
import time

import jwt
import pytest

from common import passwords, validation
from common.auth_jwt import issue_token, require_auth
from common.errors import Forbidden, Unauthorized, ValidationError
from common.http import make_handler, parse_body

SECRET = "test-secret-that-is-long-enough-1234567890"


def bearer(token):
    return {"headers": {"Authorization": f"Bearer {token}"}}


# ---------- passwords ----------

def test_hash_roundtrip_and_salt():
    h1 = passwords.hash_password("Secreta123")
    h2 = passwords.hash_password("Secreta123")
    assert h1 != h2  # random salt
    assert len(h1) <= 255
    assert passwords.verify_password("Secreta123", h1)
    assert not passwords.verify_password("secreta123", h1)


def test_verify_rejects_garbage_hash():
    assert not passwords.verify_password("x", "not-a-hash")
    assert not passwords.verify_password("x", "bcrypt$1$2$3$aa$bb")


# ---------- JWT ----------

def test_token_roundtrip():
    token, _ = issue_token(7, "buyer", 3)
    p = require_auth(bearer(token), seller=True)
    assert (p.user_id, p.role, p.seller_id, p.is_seller) == (7, "buyer", 3, True)


def test_non_seller_is_forbidden_on_seller_routes():
    token, _ = issue_token(7, "buyer", None)
    with pytest.raises(Forbidden):
        require_auth(bearer(token), seller=True)


def test_buyer_is_forbidden_on_admin_routes():
    token, _ = issue_token(7, "buyer", 3)
    with pytest.raises(Forbidden):
        require_auth(bearer(token), role="admin")


@pytest.mark.parametrize("token", [
    "",
    "abc.def.ghi",
    jwt.encode({"sub": "1", "role": "seller", "iat": 0, "exp": 9999999999, "iss": "marketplace-api"},
               "another-secret-that-is-long-enough-123456", algorithm="HS256"),
    jwt.encode({"sub": "1", "role": "seller", "iat": 0, "exp": int(time.time()) - 10, "iss": "marketplace-api"},
               SECRET, algorithm="HS256"),
    jwt.encode({"sub": "1", "role": "admin", "iat": 0, "exp": 9999999999, "iss": "marketplace-api"},
               None, algorithm="none"),
    # wrong issuer
    jwt.encode({"sub": "1", "role": "buyer", "iat": 0, "exp": 9999999999, "iss": "someone-else"},
               SECRET, algorithm="HS256"),
])
def test_bad_tokens_rejected(token):
    with pytest.raises(Unauthorized):
        require_auth(bearer(token))


def test_missing_header_rejected():
    with pytest.raises(Unauthorized):
        require_auth({"headers": {}})


# ---------- validation / parsing ----------

def test_parse_body_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        parse_body({"body": json.dumps({"email": "a@b.co", "role": "admin"})}, {"email"})


@pytest.mark.parametrize("body", ["[1,2]", "not json", '"text"'])
def test_parse_body_rejects_non_objects(body):
    with pytest.raises(ValidationError):
        parse_body({"body": body}, {"x"})


def test_email_normalised():
    assert validation.email({"email": "  Ana@Test.COM "}) == "ana@test.com"


@pytest.mark.parametrize("value", ["no-at-sign", "a@b", "a@b.c", "x" * 95 + "@b.com", "a@b.com\x00"])
def test_email_invalid(value):
    with pytest.raises(ValidationError):
        validation.email({"email": value})


@pytest.mark.parametrize("value", ["short1", "onlyletters", "12345678", "a1" * 65])
def test_password_policy(value):
    with pytest.raises(ValidationError):
        validation.new_password({"password": value})


def test_integer_rejects_bool_and_float():
    for v in (True, 1.5, "3"):
        with pytest.raises(ValidationError):
            validation.integer({"q": v}, "q", min_value=1, max_value=10)


@pytest.mark.parametrize("value", [0, -1, "1.001", "nan", "inf", True])
def test_money_invalid(value):
    with pytest.raises(ValidationError):
        validation.money({"m": value}, "m")


# ---------- handler wrapper ----------

def test_unexpected_errors_do_not_leak_details():
    def boom(event):
        raise RuntimeError("secret internal detail: password=hunter2")

    handler = make_handler({"GET /x": boom})
    resp = handler({"routeKey": "GET /x"}, None)
    assert resp["statusCode"] == 500
    assert "hunter2" not in resp["body"]


def test_unknown_route_is_404():
    resp = make_handler({})({"routeKey": "GET /nope"}, None)
    assert resp["statusCode"] == 404
