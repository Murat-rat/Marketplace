"""Product reads and DynamoDB operations for the authenticated shopping cart."""

import os
import time

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

_CART_TTL_SECONDS = 30 * 24 * 60 * 60

# Same limits as sp_place_order (migration 002), so every cart can be checked out.
MAX_LINES = 50          # different products in one cart
MAX_QUANTITY = 100      # units of one product

_table = None

# A product can be bought only while the product, its store and its category are
# active (the same rule the catalog uses). seller_user_id lets the handler stop a
# seller from putting their own products in the cart.
_PRODUCT_COLUMNS = """
    SELECT p.id, p.name, p.price, p.stock,
           (p.is_active AND s.is_active AND c.is_active) AS is_active,
           s.user_id AS seller_user_id
      FROM products p
      JOIN sellers s    ON s.id = p.seller_id
      JOIN categories c ON c.id = p.category_id
"""


class CartLimitReached(Exception):
    """The quantity would go over the stock or MAX_QUANTITY."""


class CartFull(Exception):
    """The cart already holds MAX_LINES different products."""


class CartItemNotFound(Exception):
    """The requested product is not present in this user's cart."""


def get_product(cur, product_id: int) -> dict | None:
    cur.execute(_PRODUCT_COLUMNS + " WHERE p.id = %s", (product_id,))
    return cur.fetchone()


def get_products(cur, product_ids: list[int]) -> dict[int, dict]:
    if not product_ids:
        return {}
    # The cart holds at most MAX_LINES products, so this is one bounded query.
    # Only "%s" placeholders are built here; the ids themselves are parameters.
    placeholders = ", ".join(["%s"] * len(product_ids))
    cur.execute(_PRODUCT_COLUMNS + f" WHERE p.id IN ({placeholders})", tuple(product_ids))
    return {int(row["id"]): row for row in cur.fetchall()}


def _cart_table():
    global _table
    if _table is None:
        name = os.environ.get("CART_TABLE_NAME", "t_shopping_cart")
        _table = boto3.resource("dynamodb").Table(name)
    return _table


def _is_conditional_failure(err: ClientError) -> bool:
    return err.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def _delete_if_expired(user_id: int, product_id: int, now: int) -> None:
    """Remove a stale row before an add, even if DynamoDB TTL has not run yet."""
    try:
        _cart_table().delete_item(
            Key={"user_id": user_id, "product_id": product_id},
            ConditionExpression=Attr("expiration").lte(now),
        )
    except ClientError as err:
        if not _is_conditional_failure(err):
            raise


def _has_live_item(user_id: int, product_id: int, now: int) -> bool:
    item = _cart_table().get_item(
        Key={"user_id": user_id, "product_id": product_id}, ConsistentRead=True,
    ).get("Item")
    return item is not None and int(item.get("expiration", 0)) > now


def count_items(user_id: int) -> int:
    """Number of different (not expired) products in the cart."""
    now = int(time.time())
    args = {
        "KeyConditionExpression": Key("user_id").eq(user_id),
        "FilterExpression": Attr("expiration").gt(now),
        "Select": "COUNT",
        "ConsistentRead": True,
    }
    total = 0
    while True:
        result = _cart_table().query(**args)
        total += result.get("Count", 0)
        if "LastEvaluatedKey" not in result:
            return total
        args["ExclusiveStartKey"] = result["LastEvaluatedKey"]


def add_one(user_id: int, product_id: int, stock: int) -> int:
    """Atomically add exactly one unit, capped at the stock just read from MySQL
    and at MAX_QUANTITY. A new product is refused once the cart has MAX_LINES."""
    now = int(time.time())
    _delete_if_expired(user_id, product_id, now)
    # Two simultaneous adds of *different* new products could both pass this
    # check and leave 51 lines; sp_place_order still refuses more than 50 at checkout.
    if not _has_live_item(user_id, product_id, now) and count_items(user_id) >= MAX_LINES:
        raise CartFull
    try:
        result = _cart_table().update_item(
            Key={"user_id": user_id, "product_id": product_id},
            UpdateExpression="SET #expiration = :expiration ADD #quantity :one",
            ConditionExpression="attribute_not_exists(#quantity) OR #quantity < :cap",
            ExpressionAttributeNames={"#expiration": "expiration", "#quantity": "quantity"},
            ExpressionAttributeValues={
                ":expiration": now + _CART_TTL_SECONDS,
                ":one": 1,
                ":cap": min(stock, MAX_QUANTITY),
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as err:
        if _is_conditional_failure(err):
            raise CartLimitReached from None
        raise
    return int(result["Attributes"]["quantity"])


def list_items(user_id: int) -> list[dict]:
    now = int(time.time())
    table = _cart_table()
    items: list[dict] = []
    query_args = {
        "KeyConditionExpression": Key("user_id").eq(user_id),
        "FilterExpression": Attr("expiration").gt(now),
        "ConsistentRead": True,
    }
    while True:
        result = table.query(**query_args)
        items.extend(result.get("Items", []))
        last_key = result.get("LastEvaluatedKey")
        if not last_key or len(items) >= MAX_LINES:
            break
        query_args["ExclusiveStartKey"] = last_key
    return items[:MAX_LINES]


def set_quantity(user_id: int, product_id: int, quantity: int, stock: int) -> None:
    """Set the quantity of a product that is already (and still) in the cart."""
    if quantity > min(stock, MAX_QUANTITY):
        raise CartLimitReached
    now = int(time.time())
    try:
        _cart_table().update_item(
            Key={"user_id": user_id, "product_id": product_id},
            UpdateExpression="SET #quantity = :quantity, #expiration = :expiration",
            # An expired row (TTL not run yet) counts as "not in the cart".
            ConditionExpression="attribute_exists(#quantity) AND #expiration > :now",
            ExpressionAttributeNames={"#quantity": "quantity", "#expiration": "expiration"},
            ExpressionAttributeValues={
                ":quantity": quantity,
                ":expiration": now + _CART_TTL_SECONDS,
                ":now": now,
            },
        )
    except ClientError as err:
        if _is_conditional_failure(err):
            raise CartItemNotFound from None
        raise


def remove_item(user_id: int, product_id: int) -> None:
    _cart_table().delete_item(Key={"user_id": user_id, "product_id": product_id})
