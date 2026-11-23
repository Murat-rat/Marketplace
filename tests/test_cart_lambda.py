"""cart Lambda tests: auth, limits, visibility, ownership and DynamoDB conditions.

DynamoDB is replaced by FakeTable, which applies the same conditions the real
table would (stock cap, expired rows, existing rows), so the repository logic
itself is tested, not just the handler.
"""

import importlib.util
import json
import sys
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from common.auth_jwt import issue_token

CART_DIR = Path(__file__).resolve().parents[1] / "backend" / "lambdas" / "cart"
BUYER, OTHER = 1, 2


def _conditional_failure(op):
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "failed"}}, op)


class FakeTable:
    """In-memory t_shopping_cart that honours the conditions used by repository.py."""

    def __init__(self):
        self.rows = {}  # (user_id, product_id) -> {"quantity", "expiration"}

    def put(self, user_id, product_id, quantity, expires_in=3600):
        self.rows[(user_id, product_id)] = {
            "user_id": user_id, "product_id": product_id,
            "quantity": Decimal(quantity), "expiration": Decimal(int(time.time()) + expires_in),
        }

    @staticmethod
    def _key(Key):
        return Key["user_id"], Key["product_id"]

    def get_item(self, Key, ConsistentRead=False):
        row = self.rows.get(self._key(Key))
        return {"Item": dict(row)} if row else {}

    def delete_item(self, Key, ConditionExpression=None):
        key = self._key(Key)
        if ConditionExpression is not None:  # Attr("expiration").lte(now)
            now = ConditionExpression.get_expression()["values"][1]
            row = self.rows.get(key)
            if row is None or not row["expiration"] <= now:
                raise _conditional_failure("DeleteItem")
        self.rows.pop(key, None)
        return {}

    def update_item(self, Key, UpdateExpression, ConditionExpression, ExpressionAttributeNames,
                    ExpressionAttributeValues, ReturnValues=None):
        key = self._key(Key)
        row = self.rows.get(key)
        values = ExpressionAttributeValues
        if "ADD" in UpdateExpression:  # add_one
            if row is not None and not row["quantity"] < values[":cap"]:
                raise _conditional_failure("UpdateItem")
            quantity = (row["quantity"] if row else 0) + values[":one"]
        else:  # set_quantity
            if row is None or not row["expiration"] > values[":now"]:
                raise _conditional_failure("UpdateItem")
            quantity = values[":quantity"]
        self.rows[key] = {"user_id": key[0], "product_id": key[1],
                          "quantity": Decimal(quantity), "expiration": Decimal(values[":expiration"])}
        return {"Attributes": dict(self.rows[key])}

    def query(self, KeyConditionExpression, FilterExpression, ConsistentRead=False,
              Select=None, ExclusiveStartKey=None):
        user_id = KeyConditionExpression.get_expression()["values"][1]
        now = FilterExpression.get_expression()["values"][1]
        items = [dict(r) for (u, _), r in sorted(self.rows.items()) if u == user_id and r["expiration"] > now]
        return {"Count": len(items)} if Select == "COUNT" else {"Items": items}


def product(pid, *, price="100.00", stock=3, active=True, seller_user_id=99, name=None):
    return {"id": pid, "name": name or f"Product {pid}", "price": Decimal(price), "stock": stock,
            "is_active": 1 if active else 0, "seller_user_id": seller_user_id}


PRODUCTS = {
    7: product(7, price="100.00", stock=3),
    8: product(8, stock=0),
    9: product(9, price="50.00", active=False),      # its store or category is disabled
    10: product(10, seller_user_id=BUYER),            # the buyer's own product
    11: product(11, stock=500),
}


def lookup(pid):
    if pid >= 1000:  # plenty of ordinary products for the cart-size tests
        return product(pid, stock=5)
    return PRODUCTS.get(pid)


@pytest.fixture
def cart(monkeypatch):
    sys.path.insert(0, str(CART_DIR))
    sys.modules.pop("repository", None)
    spec = importlib.util.spec_from_file_location("cart_handler", CART_DIR / "handler.py")
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    sys.path.remove(str(CART_DIR))

    @contextmanager
    def transaction(prefix):
        assert prefix == "CORE"  # the cart must never touch RDS #2
        yield object()

    monkeypatch.setattr(handler.db, "transaction", transaction)
    monkeypatch.setattr(handler.repo, "get_product", lambda cur, pid: lookup(pid))
    monkeypatch.setattr(handler.repo, "get_products",
                        lambda cur, ids: {i: lookup(i) for i in ids if lookup(i) is not None})
    handler.table = FakeTable()
    monkeypatch.setattr(handler.repo, "_table", handler.table)
    return handler


def call(handler, route, body=None, path=None, user=BUYER, token=True):
    headers = {}
    if token:
        headers["authorization"] = "Bearer " + issue_token(user, "buyer", None)[0]
    event = {"routeKey": route, "headers": headers, "pathParameters": path,
             "body": json.dumps(body) if body is not None else None}
    resp = handler.lambda_handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


def add(handler, pid, user=BUYER):
    return call(handler, "POST /cart/items", {"product_id": pid}, user=user)


def set_qty(handler, pid, body, user=BUYER):
    return call(handler, "PATCH /cart/items/{product_id}", body, path={"product_id": str(pid)}, user=user)


# ---------- auth ----------

@pytest.mark.parametrize("route, body, path", [
    ("GET /cart", None, None),
    ("POST /cart/items", {"product_id": 7}, None),
    ("PATCH /cart/items/{product_id}", {"quantity": 1}, {"product_id": "7"}),
    ("DELETE /cart/items/{product_id}", None, {"product_id": "7"}),
])
def test_every_route_requires_login(cart, route, body, path):
    assert call(cart, route, body, path, token=False)[0] == 401
    assert cart.table.rows == {}


# ---------- adding ----------

def test_add_increments_up_to_stock(cart):
    assert add(cart, 7) == (200, {"product_id": 7, "quantity": 1})
    add(cart, 7)
    assert add(cart, 7)[1]["quantity"] == 3
    status, body = add(cart, 7)  # stock is 3
    assert status == 409 and "available stock" in body["message"]
    assert cart.table.rows[(BUYER, 7)]["quantity"] == 3


def test_quantity_capped_at_100_even_with_more_stock(cart):
    cart.table.put(BUYER, 11, 100)
    assert add(cart, 11)[0] == 409
    assert cart.table.rows[(BUYER, 11)]["quantity"] == 100


@pytest.mark.parametrize("pid, status", [(8, 409), (9, 404), (500, 404), (10, 409)])
def test_add_rejects_unbuyable_products(cart, pid, status):
    # 8 out of stock, 9 hidden (store/category disabled), 500 missing, 10 the buyer's own product
    assert add(cart, pid)[0] == status
    assert cart.table.rows == {}


def test_cart_holds_at_most_50_products(cart):
    for pid in range(1000, 1050):
        cart.table.put(BUYER, pid, 1)
    status, body = add(cart, 7)
    assert status == 409 and "50" in body["message"]
    assert add(cart, 1000)[0] == 200  # a product already in the cart can still go up


def test_expired_row_starts_again_from_one(cart):
    cart.table.put(BUYER, 7, 3, expires_in=-10)  # TTL has not deleted it yet
    assert add(cart, 7) == (200, {"product_id": 7, "quantity": 1})


@pytest.mark.parametrize("body", [
    {"product_id": "7"}, {"product_id": 0}, {"product_id": True}, {"product_id": 2**31},
    {}, {"product_id": 7, "price": "0.01"}, {"product_id": 7, "user_id": OTHER},
])
def test_add_rejects_bad_input(cart, body):
    status, _ = call(cart, "POST /cart/items", body)
    assert status == 400
    assert cart.table.rows == {}


# ---------- changing quantities ----------

def test_set_quantity(cart):
    cart.table.put(BUYER, 7, 1)
    assert set_qty(cart, 7, {"quantity": 3}) == (200, {"product_id": 7, "quantity": 3})
    assert set_qty(cart, 7, {"quantity": 4})[0] == 409            # more than the stock
    assert set_qty(cart, 7, {"quantity": 0})[0] == 200            # 0 removes it
    assert (BUYER, 7) not in cart.table.rows


@pytest.mark.parametrize("body", [{"quantity": 101}, {"quantity": -1}, {"quantity": "2"},
                                  {"quantity": 2, "stock": 99}])
def test_set_quantity_rejects_bad_input(cart, body):
    cart.table.put(BUYER, 7, 1)
    assert set_qty(cart, 7, body)[0] == 400
    assert cart.table.rows[(BUYER, 7)]["quantity"] == 1


def test_set_quantity_only_for_items_in_the_cart(cart):
    assert set_qty(cart, 7, {"quantity": 2})[0] == 404            # never added
    cart.table.put(BUYER, 7, 1, expires_in=-10)
    assert set_qty(cart, 7, {"quantity": 2})[0] == 404            # expired
    assert set_qty(cart, 9, {"quantity": 1})[0] == 404            # no longer visible


@pytest.mark.parametrize("pid", ["7abc", "-1", "99999999999"])
def test_bad_path_id(cart, pid):
    assert call(cart, "DELETE /cart/items/{product_id}", path={"product_id": pid})[0] == 400


# ---------- reading ----------

def test_cart_prices_come_from_db_and_subtotal_skips_unavailable(cart):
    cart.table.put(BUYER, 7, 2)    # 2 x 100.00
    cart.table.put(BUYER, 9, 1)    # hidden product: listed, not counted
    cart.table.put(BUYER, 8, 1)    # out of stock: listed, not counted
    cart.table.put(BUYER, 11, 1, expires_in=-10)  # expired: not listed
    status, body = call(cart, "GET /cart")
    assert status == 200
    assert body["subtotal"] == "200.00" and body["item_count"] == 3
    lines = {line["product_id"]: line for line in body["items"]}
    assert lines[7]["unit_price"] == "100.00" and lines[7]["available"] is True
    assert lines[9]["available"] is False and lines[8]["available"] is False
    assert 11 not in lines


def test_users_never_see_or_change_each_others_cart(cart):
    cart.table.put(OTHER, 7, 2)
    assert call(cart, "GET /cart")[1]["items"] == []
    assert set_qty(cart, 7, {"quantity": 1})[0] == 404
    call(cart, "DELETE /cart/items/{product_id}", path={"product_id": "7"})
    assert cart.table.rows[(OTHER, 7)]["quantity"] == 2
