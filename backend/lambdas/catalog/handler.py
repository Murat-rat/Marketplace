"""catalog Lambda: browse categories and products (read-only).

GET /categories
GET /products?q=&category_id=&sort=&in_stock=&page=&page_size=
GET /products/{id}

Uses MySQL user app_catalog (RDS #1, SELECT only). No access to RDS #2.
All routes require a signed-in user.
"""

import re

from common import db, validation
from common.auth_jwt import require_auth
from common.errors import NotFound, ValidationError
from common.http import make_handler, parse_query, query_int
from common.s3_urls import image_url

import repository as repo

MAX_PAGE_SIZE = 50
MAX_TERMS = 8
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def build_search(q: str | None) -> tuple[str | None, str | None]:
    """Turn free text into a safe search.

    Returns (fulltext, like): a BOOLEAN MODE expression built ONLY from word
    characters (so users cannot inject operators like -, ~, ", @), or, when
    every word is shorter than MySQL's 3-character full-text minimum, a LIKE
    pattern with % and _ escaped.
    """
    if not q or not q.strip():
        return None, None
    words = _WORD_RE.findall(q)[:MAX_TERMS]
    long_words = [w for w in words if len(w) >= 3]
    if long_words:
        return " ".join(f"+{w}*" for w in long_words), None
    if words:
        escaped = "".join(words[:1]).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return None, f"%{escaped}%"
    return None, None


def _summary(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "price": row["price"],
        "available": row["stock"] > 0,
        "stock": row["stock"],
        "average_rating": row["average_rating"],
        "review_count": row["review_count"],
        "category_id": row["category_id"],
        "seller": {"id": row["seller_id"], "store_name": row["store_name"]},
        "image_url": image_url(row["image"]),
    }


def categories(event):
    require_auth(event)
    with db.transaction(db.CORE) as cur:
        rows = repo.list_categories(cur)
    return 200, {"categories": rows}


def products(event):
    require_auth(event)
    params = parse_query(event, {"q", "category_id", "sort", "in_stock", "page", "page_size"})
    sort = params.get("sort") or "newest"
    if sort not in repo.ORDER_BY:
        raise ValidationError(f"'sort' must be one of: {', '.join(repo.ORDER_BY)}", "sort")
    in_stock = params.get("in_stock", "0")
    if in_stock not in ("0", "1"):
        raise ValidationError("'in_stock' must be 0 or 1", "in_stock")
    category_id = query_int(params, "category_id", default=None, min_value=1, max_value=2**31 - 1)
    page = query_int(params, "page", default=1, min_value=1, max_value=1000)
    page_size = query_int(params, "page_size", default=20, min_value=1, max_value=MAX_PAGE_SIZE)
    fulltext, like = build_search(params.get("q"))

    with db.transaction(db.CORE) as cur:
        total, rows = repo.search_products(
            cur, fulltext=fulltext, like=like, category_id=category_id, in_stock=in_stock == "1",
            sort=sort, limit=page_size, offset=(page - 1) * page_size,
        )
    return 200, {
        "items": [_summary(r) for r in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, -(-total // page_size)),
    }


def product_detail(event):
    require_auth(event)
    product_id = validation.path_id(event, "id")
    with db.transaction(db.CORE) as cur:
        row = repo.get_product(cur, product_id)
        if row is None:
            raise NotFound("This product does not exist or is no longer available")
        images = repo.get_images(cur, product_id)
        path = repo.get_category_path(cur, row["category_id"])

    return 200, {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "price": row["price"],
        "available": row["stock"] > 0,
        "stock": row["stock"],
        "average_rating": row["average_rating"],
        "review_count": row["review_count"],
        "published_at": row["published_at"],
        "category_path": path,
        "seller": {
            "id": row["seller_id"],
            "store_name": row["store_name"],
            "description": row["store_description"] or "",
        },
        "images": [u for u in (image_url(i["url"]) for i in images) if u],
    }


lambda_handler = make_handler({
    "GET /categories": categories,
    "GET /products": products,
    "GET /products/{id}": product_detail,
})
