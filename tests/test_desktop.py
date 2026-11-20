"""Desktop app tests: API client (with a fake HTTP layer) and screen flows (offscreen Qt)."""

import os
import sys
from pathlib import Path

import pytest
import requests

DESKTOP = Path(__file__).resolve().parents[1] / "desktop"
sys.path.insert(0, str(DESKTOP))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from api_client import ApiClient, ApiError  # noqa: E402
from session import Session  # noqa: E402
import config  # noqa: E402

USER = {"id": 1, "name": "Ana", "email": "ana@test.com", "role": "buyer", "seller_id": None}


class FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.ok = 200 <= status < 300

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def empty_catalog(method, url, params):
    if url.endswith("/categories"):
        return FakeResponse(200, {"categories": []})
    if url.endswith("/products"):
        return FakeResponse(200, {"items": [], "page": 1, "page_size": 20, "total": 0, "pages": 1})
    return FakeResponse(404, {"error": "not_found", "message": "Not found"})


def make_client(monkeypatch, responses):
    sent = []

    def fake_request(self, method, url, json=None, headers=None, timeout=None, params=None):
        sent.append({"method": method, "url": url, "json": json, "headers": headers or {}, "params": params})
        if callable(responses):
            result = responses(method, url, params)
        elif responses:
            result = responses.pop(0)
        else:  # once the scripted answers run out, serve an empty catalog
            result = empty_catalog(method, url, params)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return ApiClient("https://api.example.com", Session()), sent


# ---------- API client ----------

def test_login_starts_session(monkeypatch):
    api, sent = make_client(monkeypatch, [FakeResponse(200, {"token": "t", "expires_in": 3600, "user": USER})])
    api.login("ana@test.com", "Secreta123")
    assert api.session.active and api.session.user.name == "Ana"
    assert sent[0]["url"] == "https://api.example.com/login"
    assert "Authorization" not in sent[0]["headers"]


def test_server_error_message_and_field(monkeypatch):
    api, _ = make_client(monkeypatch, [FakeResponse(409, {"error": "conflict", "message": "Email taken", "field": "email"})])
    with pytest.raises(ApiError) as exc:
        api.register(name="Ana", email="a@b.co", password="Secreta123", account_type="buyer")
    assert (exc.value.status, exc.value.field, exc.value.message) == (409, "email", "Email taken")


def test_register_buyer_sends_no_store_fields(monkeypatch):
    api, sent = make_client(monkeypatch, [FakeResponse(201, {"token": "t", "expires_in": 3600, "user": USER})])
    api.register(name="Ana", email="a@b.co", password="Secreta123", account_type="buyer",
                 store_name="ignored")
    assert "store_name" not in sent[0]["json"] and "phone" not in sent[0]["json"]


@pytest.mark.parametrize("failure, code", [
    (requests.ConnectionError(), "network"),
    (requests.Timeout(), "network"),
    (FakeResponse(429, {"message": "Too Many Requests"}), "throttled"),
    (FakeResponse(502, None), "error"),
])
def test_network_and_gateway_failures(monkeypatch, failure, code):
    api, _ = make_client(monkeypatch, [failure])
    with pytest.raises(ApiError) as exc:
        api.login("a@b.co", "x")
    assert exc.value.code == code and exc.value.message


def test_expired_session_has_no_token():
    s = Session()
    s.start("t", 10, USER)  # shorter than the safety margin -> already expired
    assert not s.active and s.token is None


def test_config_refuses_plain_http(monkeypatch):
    monkeypatch.setenv("API_URL", "http://evil.example.com")
    with pytest.raises(RuntimeError):
        config.api_url()
    monkeypatch.setenv("API_URL", "https://ok.example.com/")
    assert config.api_url() == "https://ok.example.com"


# ---------- screens ----------

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    from ui.theme import STYLESHEET
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    return app


def wait_for_tasks(qapp):
    from PySide6.QtCore import QThreadPool
    QThreadPool.globalInstance().waitForDone(5000)
    for _ in range(5):
        qapp.processEvents()


def test_login_flow(qapp, monkeypatch):
    from ui.main_window import MainWindow
    api, _ = make_client(monkeypatch, [
        FakeResponse(401, {"error": "unauthorized", "message": "Invalid email or password, or the account is locked."}),
        FakeResponse(200, {"token": "t", "expires_in": 3600, "user": USER}),
    ])
    win = MainWindow(api)

    # Client-side validation blocks a bad email without calling the server.
    win.login.email.input.setText("not-an-email")
    win.login._on_submit()
    assert win.login.email.error.text()

    win.login.email.input.setText("ana@test.com")
    win.login.password.input.setText("wrong")
    win.login._on_submit()
    wait_for_tasks(qapp)
    assert "Invalid email" in win.login.error.text()
    assert win.login.password.text() == ""  # rejected password is cleared

    win.login.password.input.setText("Secreta123")
    win.login._on_submit()
    wait_for_tasks(qapp)
    assert win.stack.currentWidget() is win.home
    assert win.home.user_label.text() == "ana@test.com"
    assert win.home.badge.text() == "Buyer"

    win.home.logout_requested.emit()
    assert win.stack.currentWidget() is win.login and not api.session.active


def test_register_validation_and_server_field_error(qapp, monkeypatch):
    from ui.main_window import MainWindow
    api, sent = make_client(monkeypatch, [
        FakeResponse(409, {"error": "conflict", "message": "An account with this email already exists", "field": "email"}),
    ])
    win = MainWindow(api)
    win.login.go_register.emit()
    reg = win.register
    assert not reg.store_name.isVisibleTo(reg)

    reg.as_seller.setChecked(True)
    assert reg.store_name.isVisibleTo(reg)
    reg.name.input.setText("Ana Test")
    reg.email.input.setText("ana@test.com")
    reg.password.input.setText("Secreta123")
    reg.confirm.input.setText("Different1")
    reg._on_submit()
    assert reg.confirm.error.text() and reg.store_name.error.text()
    assert sent == []  # nothing sent while the form is invalid

    reg.confirm.input.setText("Secreta123")
    reg.store_name.input.setText("Ana's Shop")
    reg._on_submit()
    wait_for_tasks(qapp)
    assert sent[0]["json"]["account_type"] == "seller"
    assert "already exists" in reg.email.error.text()


# ---------- catalog screens ----------

CATEGORIES = [
    {"id": 1, "parent_category_id": None, "name": "Electronics"},
    {"id": 2, "parent_category_id": 1, "name": "Phones"},
    {"id": 3, "parent_category_id": None, "name": "Books"},
]


def product(pid, name, available=True):
    return {"id": pid, "name": name, "price": "99.50", "available": available, "stock": 3 if available else 0,
            "average_rating": "4.0", "review_count": 1, "category_id": 2,
            "seller": {"id": 1, "store_name": "Demo Store"}, "image_url": None}


def catalog_router(expired=False):
    def route(method, url, params):
        if expired:
            return FakeResponse(401, {"error": "unauthorized", "message": "Missing or invalid authorization token"})
        if url.endswith("/categories"):
            return FakeResponse(200, {"categories": CATEGORIES})
        if url.endswith("/products"):
            items = [product(i, f"Item {i}", available=i % 2 == 0) for i in range(1, 6)]
            return FakeResponse(200, {"items": items, "page": params["page"], "page_size": 20, "total": 45, "pages": 3})
        if "/products/" in url:
            return FakeResponse(200, {**product(4, "<b>Item 4</b>"), "description": "Nice", "published_at": None,
                                      "category_path": [{"id": 1, "name": "Electronics"}, {"id": 2, "name": "Phones"}],
                                      "seller": {"id": 1, "store_name": "Demo Store", "description": ""},
                                      "images": []})
        raise AssertionError(url)
    return route


def signed_in_window(qapp, monkeypatch, router):
    from ui.main_window import MainWindow
    api, sent = make_client(monkeypatch, router)
    api.session.start("t", 3600, USER)
    win = MainWindow(api)
    win.resize(1180, 760)
    win._enter_app()
    wait_for_tasks(qapp)
    return win, sent


def test_catalog_loads_tree_grid_and_pages(qapp, monkeypatch):
    win, sent = signed_in_window(qapp, monkeypatch, catalog_router())
    shell = win.home
    assert shell.tree.topLevelItemCount() == 3  # All products, Electronics, Books
    assert shell.tree.topLevelItem(1).child(0).text(0) == "Phones"
    assert len(shell.list_page._cards) == 5
    assert shell.list_page.page_label.text() == "Page 1 of 3"
    assert not shell.list_page.prev_btn.isEnabled() and shell.list_page.next_btn.isEnabled()

    shell.list_page.next_btn.click()
    wait_for_tasks(qapp)
    assert sent[-1]["params"]["page"] == 2


def test_category_and_search_send_filters(qapp, monkeypatch):
    win, sent = signed_in_window(qapp, monkeypatch, catalog_router())
    shell = win.home
    phones = shell.tree.topLevelItem(1).child(0)
    shell._on_category(phones, 0)
    wait_for_tasks(qapp)
    assert sent[-1]["params"]["category_id"] == 2

    shell.search.setText("  nova  ")
    shell._on_search()
    wait_for_tasks(qapp)
    assert sent[-1]["params"]["q"] == "nova" and sent[-1]["params"]["category_id"] == 2
    assert 'Results for "nova" in Phones' == shell.list_page.heading.text()


def test_open_product_detail_shows_text_safely(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    win, _ = signed_in_window(qapp, monkeypatch, catalog_router())
    shell = win.home
    shell.list_page._cards[3].clicked.emit(4)
    wait_for_tasks(qapp)
    detail = shell.detail_page
    assert shell.pages.currentWidget() is detail
    assert detail.name.text() == "<b>Item 4</b>"
    assert detail.name.textFormat() == Qt.TextFormat.PlainText  # seller text is never rendered as HTML
    assert detail.breadcrumb.text() == "Electronics  ›  Phones"
    detail.back_requested.emit()
    assert shell.pages.currentWidget() is shell.list_page


def test_expired_session_returns_to_login(qapp, monkeypatch):
    win, _ = signed_in_window(qapp, monkeypatch, catalog_router(expired=True))
    assert win.stack.currentWidget() is win.login
    assert "expired" in win.login.notice.text()


def test_image_download_never_sends_token(monkeypatch):
    seen = {}

    class Resp:
        ok = True
        status_code = 200
        headers = {"Content-Type": "image/png"}
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def iter_content(self, n): yield b"png"

    def fake_get(self, url, **kwargs):
        seen["auth"] = self.headers.get("Authorization") or (kwargs.get("headers") or {}).get("Authorization")
        return Resp()

    monkeypatch.setattr(requests.Session, "get", fake_get)
    api = ApiClient("https://api.example.com", Session())
    api.session.start("secret-token", 3600, USER)
    assert api.download_image("https://bucket.s3.amazonaws.com/x.png") == b"png"
    assert seen["auth"] is None
    with pytest.raises(ApiError):
        api.download_image("http://insecure.example.com/x.png")
