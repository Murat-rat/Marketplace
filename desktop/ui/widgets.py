"""Small reusable widgets for forms."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget,
)


def _set_invalid(widget: QWidget, invalid: bool) -> None:
    widget.setProperty("invalid", "true" if invalid else "false")
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class Field(QWidget):
    """Label + input + inline error message."""

    def __init__(self, label: str, *, password: bool = False, placeholder: str = "",
                 max_length: int = 255, multiline: bool = False, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel(label)
        title.setObjectName("FieldLabel")
        layout.addWidget(title)

        if multiline:
            self.input = QPlainTextEdit()
            self.input.setPlaceholderText(placeholder)
            self.input.setFixedHeight(72)
        else:
            self.input = QLineEdit()
            self.input.setPlaceholderText(placeholder)
            self.input.setMaxLength(max_length)
            if password:
                self.input.setEchoMode(QLineEdit.EchoMode.Password)
        title.setBuddy(self.input)
        layout.addWidget(self.input)

        self.error = QLabel()
        self.error.setObjectName("FieldError")
        self.error.setWordWrap(True)
        self.error.hide()
        layout.addWidget(self.error)

    def text(self) -> str:
        if isinstance(self.input, QPlainTextEdit):
            return self.input.toPlainText()
        return self.input.text()

    def clear(self) -> None:
        self.input.clear()
        self.set_error(None)

    def set_error(self, message: str | None) -> None:
        self.error.setText(message or "")
        self.error.setVisible(bool(message))
        _set_invalid(self.input, bool(message))


class MessageBox(QLabel):
    """Inline banner for form-level errors or notices."""

    def __init__(self, kind: str = "error", parent=None):
        super().__init__(parent)
        self.setObjectName("FormError" if kind == "error" else "Notice")
        self.setWordWrap(True)
        self.hide()

    def show_message(self, text: str | None) -> None:
        self.setText(text or "")
        self.setVisible(bool(text))


def centered_card(page: QWidget, width: int = 420) -> QVBoxLayout:
    """Put a white card in the middle of `page`; return the card's layout."""
    page.setObjectName("Page")
    outer = QVBoxLayout(page)
    outer.addStretch(1)
    row = QHBoxLayout()
    row.addStretch(1)
    card = QFrame()
    card.setObjectName("Card")
    card.setFixedWidth(width)
    row.addWidget(card)
    row.addStretch(1)
    outer.addLayout(row)
    outer.addStretch(1)

    layout = QVBoxLayout(card)
    layout.setContentsMargins(32, 28, 32, 28)
    layout.setSpacing(12)
    layout.setAlignment(Qt.AlignmentFlag.AlignTop)
    return layout
