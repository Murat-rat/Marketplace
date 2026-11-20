"""Product grid: results of a search and/or category, with sorting and pages."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from api_client import ApiClient, ApiError
from ui import format as fmt
from ui.image_loader import ImageLoader
from ui.workers import run_in_background

CARD_WIDTH = 210
IMAGE_SIZE = (186, 140)
PAGE_SIZE = 20

SORTS = [
    ("Newest", "newest"),
    ("Price: low to high", "price_asc"),
    ("Price: high to low", "price_desc"),
    ("Best rated", "rating"),
]


class ProductCard(QFrame):
    clicked = Signal(int)

    def __init__(self, product: dict, images: ImageLoader, parent=None):
        super().__init__(parent)
        self.product_id = product["id"]
        self.setObjectName("ProductCard")
        self.setFixedWidth(CARD_WIDTH)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(product["name"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)

        self.image = QLabel("No image")
        self.image.setObjectName("ImagePlaceholder")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setFixedSize(*IMAGE_SIZE)
        layout.addWidget(self.image)
        images.load(product.get("image_url"), IMAGE_SIZE, self._set_image)

        name = QLabel(product["name"])
        name.setObjectName("CardTitle")
        name.setWordWrap(True)
        name.setFixedHeight(40)
        name.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(name)

        price = QLabel(fmt.money(product["price"]))
        price.setObjectName("Price")
        layout.addWidget(price)

        rating = QLabel(fmt.rating(product["average_rating"], product["review_count"]))
        rating.setObjectName("Rating")
        layout.addWidget(rating)

        store = QLabel(product["seller"]["store_name"])
        store.setObjectName("Muted")
        layout.addWidget(store)

        stock = QLabel(fmt.availability(product["available"], product.get("stock")))
        stock.setObjectName("Available" if product["available"] else "OutOfStock")
        layout.addWidget(stock)

        # Names are written by sellers: always plain text, never interpreted as HTML.
        name.setTextFormat(Qt.TextFormat.PlainText)
        store.setTextFormat(Qt.TextFormat.PlainText)

    def _set_image(self, pixmap) -> None:
        self.image.setText("")
        self.image.setPixmap(pixmap)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.product_id)
        super().mouseReleaseEvent(event)


class ProductListPage(QWidget):
    product_selected = Signal(int)
    session_expired = Signal()

    def __init__(self, api: ApiClient, images: ImageLoader, parent=None):
        super().__init__(parent)
        self.api = api
        self.images = images
        self.query = ""
        self.category_id: int | None = None
        self.category_name = "All products"
        self.page = 1
        self.pages = 1
        self._request_id = 0
        self._items: list[dict] = []
        self._cards: list[ProductCard] = []
        self._columns = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        # Header: what is being shown + sort/filter controls
        header = QHBoxLayout()
        self.heading = QLabel("All products")
        self.heading.setObjectName("SectionTitle")
        header.addWidget(self.heading)
        self.count_label = QLabel()
        self.count_label.setObjectName("Muted")
        header.addWidget(self.count_label)
        header.addStretch(1)
        self.in_stock = QCheckBox("In stock only")
        self.in_stock.toggled.connect(lambda _checked: self.reload(page=1))
        header.addWidget(self.in_stock)
        self.sort = QComboBox()
        for label, value in SORTS:
            self.sort.addItem(label, value)
        self.sort.currentIndexChanged.connect(lambda _i: self.reload(page=1))
        header.addWidget(self.sort)
        outer.addLayout(header)

        # Status line for loading / errors / empty results
        status_row = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        status_row.addWidget(self.status, 1)
        self.retry = QPushButton("Try again")
        self.retry.setObjectName("Secondary")
        self.retry.clicked.connect(lambda: self.reload())
        self.retry.hide()
        status_row.addWidget(self.retry)
        outer.addLayout(status_row)

        # The grid
        self.grid_host = QWidget()
        self.grid_host.setObjectName("Page")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(14)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self.grid_host)
        self.scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(self.scroll, 1)

        # Pager
        pager = QHBoxLayout()
        pager.addStretch(1)
        self.prev_btn = QPushButton("← Previous")
        self.prev_btn.setObjectName("Secondary")
        self.prev_btn.clicked.connect(lambda: self.reload(page=self.page - 1))
        self.page_label = QLabel()
        self.page_label.setObjectName("Muted")
        self.next_btn = QPushButton("Next →")
        self.next_btn.setObjectName("Secondary")
        self.next_btn.clicked.connect(lambda: self.reload(page=self.page + 1))
        pager.addWidget(self.prev_btn)
        pager.addWidget(self.page_label)
        pager.addWidget(self.next_btn)
        pager.addStretch(1)
        outer.addLayout(pager)
        self._update_pager()

    # ------------------------------------------------------------ public

    def show_results(self, *, query: str | None = None, category_id=..., category_name: str | None = None):
        """Change the search and/or category and load page 1."""
        if query is not None:
            self.query = query
        if category_id is not ...:
            self.category_id = category_id
        if category_name is not None:
            self.category_name = category_name
        self.reload(page=1)

    def reload(self, page: int | None = None) -> None:
        if page is not None:
            self.page = max(1, page)
        self._request_id += 1
        request_id = self._request_id
        self._set_status("Loading products…")
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)

        heading = self.category_name
        if self.query:
            heading = f'Results for "{self.query}"' + (
                f" in {self.category_name}" if self.category_id is not None else "")
        self.heading.setText(heading)

        args = dict(q=self.query, category_id=self.category_id, sort=self.sort.currentData(),
                    in_stock=self.in_stock.isChecked(), page=self.page, page_size=PAGE_SIZE)
        run_in_background(
            lambda: self.api.search_products(**args),
            lambda data: self._on_loaded(request_id, data),
            lambda err: self._on_error(request_id, err),
        )

    # ------------------------------------------------------------ results

    def _on_loaded(self, request_id: int, data: dict) -> None:
        if request_id != self._request_id:
            return  # an older request finished after a newer one: ignore it
        self.page = data["page"]
        self.pages = data["pages"]
        self._items = data["items"]
        total = data["total"]
        self.count_label.setText(f"· {total} product{'s' if total != 1 else ''}")
        if not self._items:
            self._set_status("No products match. Try other words or another category.")
        else:
            self._set_status(None)
        self._rebuild_grid(force=True)
        self._update_pager()
        self.scroll.verticalScrollBar().setValue(0)

    def _on_error(self, request_id: int, err: ApiError) -> None:
        if request_id != self._request_id:
            return
        if err.session_expired:
            self.session_expired.emit()
            return
        self._items = []
        self._rebuild_grid(force=True)
        self._set_status(err.message, retry=True)
        self._update_pager()

    def _set_status(self, text: str | None, retry: bool = False) -> None:
        self.status.setText(text or "")
        self.status.setVisible(bool(text))
        self.retry.setVisible(retry)

    def _update_pager(self) -> None:
        self.page_label.setText(f"Page {self.page} of {self.pages}")
        self.prev_btn.setEnabled(self.page > 1)
        self.next_btn.setEnabled(self.page < self.pages)

    # ------------------------------------------------------------ grid layout

    def _columns_for_width(self) -> int:
        width = self.scroll.viewport().width()
        return max(1, (width + 14) // (CARD_WIDTH + 14))

    def _rebuild_grid(self, force: bool = False) -> None:
        columns = self._columns_for_width()
        if not force and columns == self._columns:
            return
        self._columns = columns
        if force:
            for card in self._cards:
                card.deleteLater()
            self._cards = []
            for product in self._items:
                card = ProductCard(product, self.images)
                card.clicked.connect(self.product_selected.emit)
                self._cards.append(card)
        while self.grid.count():
            self.grid.takeAt(0)
        for index, card in enumerate(self._cards):
            self.grid.addWidget(card, index // columns, index % columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild_grid()
