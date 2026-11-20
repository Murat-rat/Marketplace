"""Authenticated shopping cart routes backed by DynamoDB."""

from decimal import Decimal

from common import db, validation
from common.auth_jwt import require_auth
from common.errors import Conflict, NotFound
from common.http import make_handler, parse_body

import repository as repo


def get_cart(event):
    principal = require_auth(event)
    rows = repo.list_items(principal.user_id)
    product_ids = [int(row["product_id"]) for row in rows]
    if product_ids:
        with db.transaction(db.CORE) as cur:
            products = repo.get_products(cur, product_ids)
    else:
        products = {}

    items = []
    subtotal = Decimal("0.00")
    total_quantity = 0
    for row in rows:
        product_id = int(row["product_id"])
        quantity = int(row["quantity"])
        product = products.get(product_id)
        if product is None:
            name, price, stock, active = "Unavailable product", Decimal("0.00"), 0, False
        else:
            name = product["name"]
            price = Decimal(str(product["price"]))
            stock = int(product["stock"])
            active = bool(product["is_active"])
        available = active and stock > 0 and quantity <= stock
        line_total = price * quantity
        subtotal += line_total
        total_quantity += quantity
        items.append({
            "product_id": product_id,
            "name": name,
            "unit_price": price,
            "quantity": quantity,
            "stock": stock,
            "available": available,
            "line_total": line_total,
        })

    return 200, {
        "items": items,
        "subtotal": subtotal,
        "total_quantity": total_quantity,
        "item_count": len(items),
    }


def add_item(event):
    principal = require_auth(event)
    body = parse_body(event, {"product_id"})
    product_id = validation.integer(body, "product_id", min_value=1, max_value=2**31 - 1)
    with db.transaction(db.CORE) as cur:
        product = repo.get_product(cur, product_id)
    if product is None or not product["is_active"]:
        raise NotFound("This product does not exist or is no longer available")
    if int(product["stock"]) < 1:
        raise Conflict("This product is out of stock")
    try:
        quantity = repo.add_one(principal.user_id, product_id, int(product["stock"]))
    except repo.CartLimitReached:
        raise Conflict("You cannot add more than the available stock") from None
    return 200, {"product_id": product_id, "quantity": quantity}


def update_item(event):
    principal = require_auth(event)
    product_id = validation.path_id(event, "product_id")
    body = parse_body(event, {"quantity"})
    quantity = validation.integer(body, "quantity", min_value=0, max_value=2**31 - 1)
    if quantity == 0:
        repo.remove_item(principal.user_id, product_id)
        return 200, {"product_id": product_id, "quantity": 0}

    with db.transaction(db.CORE) as cur:
        product = repo.get_product(cur, product_id)
    if product is None or not product["is_active"]:
        raise NotFound("This product does not exist or is no longer available")
    try:
        repo.set_quantity(principal.user_id, product_id, quantity, int(product["stock"]))
    except repo.CartItemNotFound:
        raise NotFound("This product is not in your cart") from None
    except repo.CartLimitReached:
        raise Conflict("The requested quantity exceeds available stock") from None
    return 200, {"product_id": product_id, "quantity": quantity}


def delete_item(event):
    principal = require_auth(event)
    product_id = validation.path_id(event, "product_id")
    repo.remove_item(principal.user_id, product_id)
    return 200, {"product_id": product_id, "removed": True}


lambda_handler = make_handler({
    "GET /cart": get_cart,
    "POST /cart/items": add_item,
    "PATCH /cart/items/{product_id}": update_item,
    "DELETE /cart/items/{product_id}": delete_item,
})
