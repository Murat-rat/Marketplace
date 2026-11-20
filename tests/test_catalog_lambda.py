"""catalog Lambda tests: search building, parameter validation, auth, and response shape."""

import importlib.util
import json
import sys
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest

from common.auth_jwt import issue_token

CATALOG_DIR = Path(__file__).resolve().parents[1] / "backend" / "lambdas" / "catalog"

PRODUCT_ROW = {
    "id": 7, "name": "Nova X5", "price": Decimal("6499.00"), "stock": 0, "average_rating": Decimal("4.5"),
    "review_count": 2, "category_id": 3, "seller_id": 1, "store_name": "Demo Store", "image": None,
}


@pytest.fixture
def catalog(monkeypatch):
    sys.path.insert(0, str(CATALOG_DIR))
    sys.modules.pop("repository", None)
    spec = importlib.util.spec_from_file_location("catalog_handler", CATALOG_DIR / "handler.py")
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    sys.path.remove(str(CATALOG_DIR))

    @contextmanager
    def transaction(prefix):
        assert prefix == "CORE"  # the catalog must never touch RDS #2
        yield object()

    monkeypatch.setattr(handler.db, "transaction", transaction)
    handler.calls = []

    def search_products(cur, **kwargs):
        handler.calls.append(kwargs)
        return 1, [PRODUCT_ROW]

    monkeypatch.setattr(handler.repo, "search_products", search_products)
    monkeypatch.setattr(handler.repo, "list_categories", lambda cur: [{"id": 1, "parent_category_id": None, "name": "Books"}])
    monkeypatch.setattr(handler.repo, "get_product",
                        lambda cur, pid: {**PRODUCT_ROW, "description": "d", "published_at": None,
                                          "store_description": None} if pid == 7 else None)
    monkeypatch.setattr(handler.repo, "get_images", lambda cur, pid: [{"url": "products/7/a.jpg"}])
    monkeypatch.setattr(handler.repo, "get_category_path", lambda cur, cid: [{"id": 1, "name": "Electronics"}])
    return handler


def call(handler, route, query=None, path=None, token=True):
    headers = {}
    if token:
        headers["authorization"] = "Bearer " + issue_token(1, "buyer", None)[0]
    event = {"routeKey": route, "headers": headers, "queryStringParameters": query, "pathParameters": path}
    resp = handler.lambda_handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


# ---------- search building ----------

def test_search_strips_boolean_operators(catalog):
    fulltext, like = catalog.build_search('phone -cheap "x" @2 ~old (a)')
    assert fulltext == "+phone* +cheap* +old*"
    assert like is None
    for char in '-"@~()<>':
        assert char not in fulltext


def test_short_words_fall_back_to_escaped_like(catalog):
    assert catalog.build_search("x5") == (None, "%x5%")
    assert catalog.build_search("a_") == (None, "%a\\_%")


def test_empty_search(catalog):
    assert catalog.build_search("   ") == (None, None)
    assert catalog.build_search("%%%") == (None, None)


# ---------- routes ----------

def test_requires_login(catalog):
    assert call(catalog, "GET /products", token=False)[0] == 401
    assert call(catalog, "GET /categories", token=False)[0] == 401


def test_products_defaults_and_shape(catalog):
    status, body = call(catalog, "GET /products")
    assert status == 200
    assert catalog.calls[0]["sort"] == "newest" and catalog.calls[0]["limit"] == 20
    item = body["items"][0]
    assert item["price"] == "6499.00" and item["available"] is False
    assert item["seller"]["store_name"] == "Demo Store"
    assert body["pages"] == 1


def test_pagination_offset(catalog):
    call(catalog, "GET /products", {"page": "3", "page_size": "10"})
    assert catalog.calls[0]["offset"] == 20


@pytest.mark.parametrize("query", [
    {"sort": "price; DROP TABLE products"},
    {"sort": "p.id"},
    {"page": "0"},
    {"page": "-1"},
    {"page_size": "500"},
    {"category_id": "1 OR 1=1"},
    {"in_stock": "yes"},
    {"seller_id": "1"},
    {"q": "x" * 300},
])
def test_rejects_bad_parameters(catalog, query):
    status, _ = call(catalog, "GET /products", query)
    assert status == 400
    assert catalog.calls == []  # nothing reached the database


def test_detail_found_and_missing(catalog):
    status, body = call(catalog, "GET /products/{id}", path={"id": "7"})
    assert status == 200 and body["category_path"][0]["name"] == "Electronics"
    assert body["images"] == []  # no IMAGES_BUCKET configured -> keys are not exposed
    assert call(catalog, "GET /products/{id}", path={"id": "999"})[0] == 404
    assert call(catalog, "GET /products/{id}", path={"id": "7abc"})[0] == 400
