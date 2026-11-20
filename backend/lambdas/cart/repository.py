"""Product reads and DynamoDB operations for the authenticated shopping cart."""

import os
import time

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

_CART_TTL_SECONDS = 30 * 24 * 60 * 60
_table = None


class CartLimitReached(Exception):
    """The cart quantity reached current product stock."""


class CartItemNotFound(Exception):
    """The requested product is not present in this user's cart."""


def get_product(cur, product_id: int) -> dict | None:
    cur.execute(
        "SELECT id, name, price, stock, is_active FROM products WHERE id = %s",
        (product_id,),
    )
    return cur.fetchone()


def get_products(cur, product_ids: list[int]) -> dict[int, dict]:
    products = {}
    # Keep the IN list bounded even if a user has accumulated a very large cart.
    for start in range(0, len(product_ids), 200):
        batch = product_ids[start:start + 200]
        placeholders = ", ".join(["%s"] * len(batch))
        cur.execute(
            f"SELECT id, name, price, stock, is_active FROM products WHERE id IN ({placeholders})",
            tuple(batch),
        )
        products.update({int(row["id"]): row for row in cur.fetchall()})
    return products


def _cart_table():
    global _table
    if _table is None:
        name = os.environ.get("CART_TABLE_NAME", "t_shopping_cart")
        _table = boto3.resource("dynamodb").Table(name)
    return _table


def _delete_if_expired(user_id: int, product_id: int, now: int) -> None:
    """Remove a stale row before an add, even if DynamoDB TTL has not run yet."""
    try:
        _cart_table().delete_item(
            Key={"user_id": user_id, "product_id": product_id},
            ConditionExpression=Attr("expiration").lte(now),
        )
    except ClientError as err:
        if err.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise


def add_one(user_id: int, product_id: int, stock: int) -> int:
    """Atomically add exactly one unit, capped at the stock just read from MySQL."""
    now = int(time.time())
    _delete_if_expired(user_id, product_id, now)
    try:
        result = _cart_table().update_item(
            Key={"user_id": user_id, "product_id": product_id},
            UpdateExpression="SET #expiration = :expiration ADD #quantity :one",
            ConditionExpression="attribute_not_exists(#quantity) OR #quantity < :stock",
            ExpressionAttributeNames={"#expiration": "expiration", "#quantity": "quantity"},
            ExpressionAttributeValues={
                ":expiration": now + _CART_TTL_SECONDS,
                ":one": 1,
                ":stock": stock,
            },
            ReturnValues="ALL_NEW",
        )
    except ClientError as err:
        if err.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
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
        if not last_key:
            break
        query_args["ExclusiveStartKey"] = last_key
    return items


def set_quantity(user_id: int, product_id: int, quantity: int, stock: int) -> None:
    if quantity == 0:
        remove_item(user_id, product_id)
        return
    if quantity > stock:
        raise CartLimitReached
    now = int(time.time())
    try:
        _cart_table().update_item(
            Key={"user_id": user_id, "product_id": product_id},
            UpdateExpression="SET #quantity = :quantity, #expiration = :expiration",
            ConditionExpression="attribute_exists(#quantity)",
            ExpressionAttributeNames={"#quantity": "quantity", "#expiration": "expiration"},
            ExpressionAttributeValues={
                ":quantity": quantity,
                ":expiration": now + _CART_TTL_SECONDS,
            },
        )
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code")
        if code == "ConditionalCheckFailedException":
            response = _cart_table().get_item(
                Key={"user_id": user_id, "product_id": product_id},
                ConsistentRead=True,
            )
            if "Item" not in response or int(response["Item"].get("expiration", 0)) <= now:
                raise CartItemNotFound from None
            raise CartLimitReached from None
        raise


def remove_item(user_id: int, product_id: int) -> None:
    _cart_table().delete_item(Key={"user_id": user_id, "product_id": product_id})
