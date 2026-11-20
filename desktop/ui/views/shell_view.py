"""The main screen after signing in: top bar, category tree and catalog pages."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QStackedWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from api_client import ApiClient, ApiError
from session import User
from ui.image_loader import ImageLoader
from ui.views.product_detail import ProductDetailPage
from ui.views.product_list import ProductListPage
from ui.workers import run_in_background

ALL_PRODUCTS = "All products"


class ShellView(QWidget):
    logout_requested = Signal()
    session_expired = Signal()

    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.images = ImageLoader(api, self)
        self.setObjectName("Page")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 16)
        outer.setSpacing(14)

        # ---------- top bar ----------
        bar = QHBoxLayout()
        bar.setSpacing(10)
        brand = QLabel("Marketplace")
        brand.setObjectName("Title")
        bar.addWidget(brand)
        bar.addSpacing(16)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search products…")
        self.search.setMaxLength(100)
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(260)
        self.search.returnPressed.connect(self._on_search)
        bar.addWidget(self.search, 1)
        search_btn = QPushButton("Search")
        search_btn.setObjectName("Primary")
        search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        search_btn.clicked.connect(self._on_search)
        bar.addWidget(search_btn)
        bar.addSpacing(16)
        self.badge = QLabel()
        self.badge.setObjectName("Badge")
        bar.addWidget(self.badge)
        self.user_label = QLabel()
        self.user_label.setObjectName("Muted")
        bar.addWidget(self.user_label)
        logout = QPushButton("Log out")
        logout.setObjectName("Secondary")
        logout.setCursor(Qt.CursorShape.PointingHandCursor)
        logout.clicked.connect(self.logout_requested.emit)
        bar.addWidget(logout)
        outer.addLayout(bar)

        # ---------- body: categories | pages ----------
        body = QHBoxLayout()
        body.setSpacing(18)

        side = QVBoxLayout()
        side.setSpacing(6)
        cat_title = QLabel("Categories")
        cat_title.setObjectName("FieldLabel")
        side.addWidget(cat_title)
        self.tree = QTreeWidget()
        self.tree.setObjectName("CategoryTree")
        self.tree.setHeaderHidden(True)
        self.tree.setFixedWidth(210)
        self.tree.itemClicked.connect(self._on_category)
        side.addWidget(self.tree, 1)
        self.categories_status = QLabel()
        self.categories_status.setObjectName("Muted")
        self.categories_status.setWordWrap(True)
        self.categories_status.hide()
        side.addWidget(self.categories_status)
        body.addLayout(side)

        self.pages = QStackedWidget()
        self.list_page = ProductListPage(api, self.images)
        self.detail_page = ProductDetailPage(api, self.images)
        self.pages.addWidget(self.list_page)
        self.pages.addWidget(self.detail_page)
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)

        self.list_page.product_selected.connect(self._open_product)
        self.detail_page.back_requested.connect(lambda: self.pages.setCurrentWidget(self.list_page))
        self.list_page.session_expired.connect(self.session_expired.emit)
        self.detail_page.session_expired.connect(self.session_expired.emit)

    # ------------------------------------------------------------ public

    def start(self, user: User) -> None:
        self.badge.setText("Seller" if user.is_seller else "Buyer")
        self.user_label.setText(user.email)
        self.search.clear()
        self.pages.setCurrentWidget(self.list_page)
        self._load_categories()
        self.list_page.show_results(query="", category_id=None, category_name=ALL_PRODUCTS)

    # ------------------------------------------------------------ categories

    def _load_categories(self) -> None:
        self.tree.clear()
        self.categories_status.setText("Loading categories…")
        self.categories_status.show()
        run_in_background(self.api.get_categories, self._fill_tree, self._categories_failed)

    def _fill_tree(self, categories: list[dict]) -> None:
        self.categories_status.hide()
        self.tree.clear()
        root = QTreeWidgetItem([ALL_PRODUCTS])
        root.setData(0, Qt.ItemDataRole.UserRole, None)
        self.tree.addTopLevelItem(root)

        items: dict[int, QTreeWidgetItem] = {}
        for c in categories:
            item = QTreeWidgetItem([c["name"]])
            item.setData(0, Qt.ItemDataRole.UserRole, c["id"])
            items[c["id"]] = item
        for c in categories:
            parent = items.get(c["parent_category_id"]) if c["parent_category_id"] else None
            if parent is not None:
                parent.addChild(items[c["id"]])
            else:
                self.tree.addTopLevelItem(items[c["id"]])
        self.tree.setCurrentItem(root)

    def _categories_failed(self, err: ApiError) -> None:
        if err.session_expired:
            self.session_expired.emit()
            return
        self.categories_status.setText(f"Categories unavailable: {err.message}")
        self.categories_status.show()

    def _on_category(self, item: QTreeWidgetItem, _column: int) -> None:
        self.pages.setCurrentWidget(self.list_page)
        self.list_page.show_results(category_id=item.data(0, Qt.ItemDataRole.UserRole),
                                    category_name=item.text(0))

    # ------------------------------------------------------------ search / detail

    def _on_search(self) -> None:
        self.pages.setCurrentWidget(self.list_page)
        self.list_page.show_results(query=self.search.text().strip())

    def _open_product(self, product_id: int) -> None:
        self.pages.setCurrentWidget(self.detail_page)
        self.detail_page.load(product_id)
