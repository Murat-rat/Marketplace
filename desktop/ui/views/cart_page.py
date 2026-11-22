"""Shopping cart screen with stock-aware quantity controls."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from api_client import ApiClient, ApiError
from ui import format as fmt
from ui.workers import run_in_background


class CartPage(QWidget):
    continue_shopping = Signal()
    cart_loaded = Signal(object)
    session_expired = Signal()

    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._request_id = 0
        self._notice_after_load: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        header = QHBoxLayout()
        self.back = QPushButton("← Continue shopping")
        self.back.setObjectName("Link")
        self.back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back.clicked.connect(self.continue_shopping.emit)
        header.addWidget(self.back)
        header.addStretch(1)
        title = QLabel("Your shopping cart")
        title.setObjectName("SectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        outer.addLayout(header)

        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

        self.empty = QLabel("Your cart is empty. Add a product to get started.")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.hide()
        outer.addWidget(self.empty)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 8, 0)
        self.rows_layout.setSpacing(10)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(self.rows_host)
        outer.addWidget(self.scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.summary = QLabel()
        self.summary.setObjectName("FieldLabel")
        footer.addWidget(self.summary)
        outer.addLayout(footer)

    def load(self, notice: str | None = None) -> None:
        self._request_id += 1
        request_id = self._request_id
        self._notice_after_load = notice
        self.status.setText("Loading your cart…")
        self.empty.hide()
        self.scroll.setEnabled(True)
        run_in_background(
            self.api.get_cart,
            lambda data: self._on_loaded(request_id, data),
            lambda err: self._on_error(request_id, err),
        )

    def reset(self) -> None:
        """Clear the last account's cart rows before another account signs in."""
        self._request_id += 1
        self._clear_rows()
        self._notice_after_load = None
        self.empty.hide()
        self.status.clear()
        self.summary.clear()
        self.scroll.setEnabled(True)

    def _on_loaded(self, request_id: int, data: dict) -> None:
        if request_id != self._request_id:
            return
        self._clear_rows()
        items = data["items"]
        if not items:
            self.status.setText(self._notice_after_load or "")
            self.empty.show()
            self.summary.setText("Subtotal: $0.00")
        else:
            self.status.setText(self._notice_after_load or "")
            self.empty.hide()
            for item in items:
                self.rows_layout.insertWidget(self.rows_layout.count() - 1, self._make_row(item))
            self.summary.setText(
                f"{data['total_quantity']} item(s) · Subtotal: {fmt.money(data['subtotal'])}"
            )
        self._notice_after_load = None
        self.cart_loaded.emit(data)

    def _on_error(self, request_id: int, err: ApiError) -> None:
        if request_id != self._request_id:
            return
        if err.session_expired:
            self.session_expired.emit()
            return
        self.empty.hide()
        self.scroll.setEnabled(True)
        self.status.setText(err.message)
        self.summary.clear()

    def _clear_rows(self) -> None:
        while self.rows_layout.count() > 1:
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _make_row(self, item: dict) -> QWidget:
        frame = QFrame()
        frame.setObjectName("Card")
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)

        details = QVBoxLayout()
        name = QLabel(item["name"])
        name.setObjectName("FieldLabel")
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setWordWrap(True)
        details.addWidget(name)
        price = QLabel(f"{fmt.money(item['unit_price'])} each")
        price.setObjectName("Muted")
        details.addWidget(price)
        if not item["available"]:
            unavailable = QLabel("Unavailable or quantity exceeds current stock")
            unavailable.setObjectName("OutOfStock")
            unavailable.setWordWrap(True)
            details.addWidget(unavailable)
        row.addLayout(details, 1)

        quantity = QLabel(str(item["quantity"]))
        quantity.setMinimumWidth(28)
        quantity.setAlignment(Qt.AlignmentFlag.AlignCenter)
        minus = QPushButton("−")
        minus.setObjectName("Secondary")
        minus.setToolTip("Remove one unit")
        minus.clicked.connect(
            lambda _checked=False, pid=item["product_id"], qty=item["quantity"]:
                self._change_quantity(pid, qty - 1)
        )
        plus = QPushButton("+")
        plus.setObjectName("Secondary")
        plus.setToolTip("Add one unit")
        limit = item.get("max_quantity", item["stock"])  # stock, capped at 100 by the server
        plus.setEnabled(bool(item["available"] and item["quantity"] < limit))
        plus.clicked.connect(
            lambda _checked=False, pid=item["product_id"], qty=item["quantity"]:
                self._change_quantity(pid, qty + 1)
        )
        quantity_box = QHBoxLayout()
        quantity_box.addWidget(minus)
        quantity_box.addWidget(quantity)
        quantity_box.addWidget(plus)
        row.addLayout(quantity_box)

        line_total = QLabel(fmt.money(item["line_total"]))
        line_total.setObjectName("FieldLabel")
        line_total.setMinimumWidth(95)
        line_total.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(line_total)

        remove = QPushButton("Remove")
        remove.setObjectName("Link")
        remove.clicked.connect(
            lambda _checked=False, pid=item["product_id"]: self._remove_item(pid)
        )
        row.addWidget(remove)
        return frame

    def _change_quantity(self, product_id: int, quantity: int) -> None:
        self.status.setText("Updating cart…")
        self.scroll.setEnabled(False)
        run_in_background(
            lambda: self.api.set_cart_quantity(product_id, quantity),
            lambda _result: self.load(),
            self._mutation_failed,
        )

    def _remove_item(self, product_id: int) -> None:
        self.status.setText("Removing product…")
        self.scroll.setEnabled(False)
        run_in_background(
            lambda: self.api.remove_cart_item(product_id),
            lambda _result: self.load(),
            self._mutation_failed,
        )

    def _mutation_failed(self, err: ApiError) -> None:
        if err.session_expired:
            self.session_expired.emit()
            return
        self.scroll.setEnabled(True)
        self.load(notice=err.message)
