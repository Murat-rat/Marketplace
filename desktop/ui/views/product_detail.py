"""One product: images, price, availability, store and description."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from api_client import ApiClient, ApiError
from ui import format as fmt
from ui.image_loader import ImageLoader
from ui.workers import run_in_background

MAIN_IMAGE = (340, 300)
THUMB = (64, 64)


class ProductDetailPage(QWidget):
    back_requested = Signal()
    session_expired = Signal()

    def __init__(self, api: ApiClient, images: ImageLoader, parent=None):
        super().__init__(parent)
        self.api = api
        self.images = images
        self.product: dict | None = None
        self._request_id = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        top = QHBoxLayout()
        back = QPushButton("← Back to products")
        back.setObjectName("Link")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.back_requested.emit)
        top.addWidget(back)
        top.addStretch(1)
        outer.addLayout(top)

        self.status = QLabel()
        self.status.setObjectName("Muted")
        outer.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll, 1)

        self.card = QFrame()
        self.card.setObjectName("Card")
        scroll.setWidget(self.card)
        body = QHBoxLayout(self.card)
        body.setContentsMargins(24, 24, 24, 24)
        body.setSpacing(28)

        # Left: images
        left = QVBoxLayout()
        left.setSpacing(8)
        self.main_image = QLabel("No image")
        self.main_image.setObjectName("ImagePlaceholder")
        self.main_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_image.setFixedSize(*MAIN_IMAGE)
        left.addWidget(self.main_image)
        self.thumbs = QHBoxLayout()
        self.thumbs.setSpacing(6)
        self.thumbs.addStretch(1)
        left.addLayout(self.thumbs)
        left.addStretch(1)
        body.addLayout(left)

        # Right: information
        right = QVBoxLayout()
        right.setSpacing(8)
        self.breadcrumb = QLabel()
        self.breadcrumb.setObjectName("Muted")
        self.name = QLabel()
        self.name.setObjectName("Title")
        self.name.setWordWrap(True)
        self.rating = QLabel()
        self.rating.setObjectName("Rating")
        self.price = QLabel()
        self.price.setObjectName("BigPrice")
        self.stock = QLabel()
        self.store = QLabel()
        self.store.setObjectName("FieldLabel")
        self.store_description = QLabel()
        self.store_description.setObjectName("Muted")
        self.store_description.setWordWrap(True)
        about = QLabel("About this product")
        about.setObjectName("FieldLabel")
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.description.setTextFormat(Qt.TextFormat.PlainText)  # never render seller text as HTML

        for widget in (self.breadcrumb, self.name, self.rating, self.price, self.stock):
            right.addWidget(widget)
        right.addSpacing(10)
        sold_by = QLabel("Sold by")
        sold_by.setObjectName("Muted")
        right.addWidget(sold_by)
        right.addWidget(self.store)
        right.addWidget(self.store_description)
        right.addSpacing(10)
        right.addWidget(about)
        right.addWidget(self.description)
        right.addStretch(1)
        body.addLayout(right, 1)

        # Seller-written text is shown as plain text, never as HTML.
        for label in (self.name, self.store, self.store_description, self.breadcrumb):
            label.setTextFormat(Qt.TextFormat.PlainText)

        self.card.hide()

    # ------------------------------------------------------------ loading

    def load(self, product_id: int) -> None:
        self._request_id += 1
        request_id = self._request_id
        self.card.hide()
        self.status.setText("Loading product…")
        self.status.show()
        run_in_background(
            lambda: self.api.get_product(product_id),
            lambda data: self._on_loaded(request_id, data),
            lambda err: self._on_error(request_id, err),
        )

    def _on_loaded(self, request_id: int, p: dict) -> None:
        if request_id != self._request_id:
            return
        self.product = p
        self.status.hide()
        self.breadcrumb.setText("  ›  ".join(c["name"] for c in p["category_path"]))
        self.name.setText(p["name"])
        self.rating.setText(fmt.rating(p["average_rating"], p["review_count"]))
        self.price.setText(fmt.money(p["price"]))
        if p["available"]:
            self.stock.setText(f"In stock · {p['stock']} available")
            self.stock.setObjectName("Available")
        else:
            self.stock.setText("Out of stock")
            self.stock.setObjectName("OutOfStock")
        self.stock.style().unpolish(self.stock)
        self.stock.style().polish(self.stock)
        self.store.setText(p["seller"]["store_name"])
        self.store_description.setText(p["seller"]["description"])
        self.store_description.setVisible(bool(p["seller"]["description"]))
        self.description.setText(p["description"] or "The seller has not added a description.")

        self._show_images(p["images"])
        self.card.show()

    def _on_error(self, request_id: int, err: ApiError) -> None:
        if request_id != self._request_id:
            return
        if err.session_expired:
            self.session_expired.emit()
            return
        self.status.setText(err.message)
        self.status.show()

    # ------------------------------------------------------------ images

    def _show_images(self, urls: list[str]) -> None:
        while self.thumbs.count() > 1:
            item = self.thumbs.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.main_image.clear()
        self.main_image.setText("No image")
        if not urls:
            return
        self._select_image(urls[0])
        if len(urls) > 1:
            for url in urls:
                thumb = QPushButton()
                thumb.setObjectName("Thumb")
                thumb.setFixedSize(THUMB[0] + 6, THUMB[1] + 6)
                thumb.setCursor(Qt.CursorShape.PointingHandCursor)
                thumb.clicked.connect(lambda _c=False, u=url: self._select_image(u))
                self.images.load(url, THUMB, lambda pm, b=thumb: (b.setIcon(pm), b.setIconSize(pm.size())))
                self.thumbs.insertWidget(self.thumbs.count() - 1, thumb)

    def _select_image(self, url: str) -> None:
        def show(pixmap):
            self.main_image.setText("")
            self.main_image.setPixmap(pixmap)
        self.images.load(url, MAIN_IMAGE, show)
