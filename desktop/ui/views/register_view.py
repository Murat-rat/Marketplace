from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QPushButton, QRadioButton, QScrollArea, QWidget,
)

import validation
from api_client import ApiClient, ApiError
from ui.widgets import Field, MessageBox, centered_card
from ui.workers import run_in_background


class RegisterView(QWidget):
    registered = Signal()
    go_login = Signal()

    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api

        # The form is taller than small screens, so it lives in a scroll area.
        content = QWidget()
        layout = centered_card(content, width=460)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(content)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        title = QLabel("Create an account")
        title.setObjectName("Title")
        subtitle = QLabel("Buy from any store, or open your own.")
        subtitle.setObjectName("Subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(4)

        self.error = MessageBox("error")
        layout.addWidget(self.error)

        type_label = QLabel("I want to")
        type_label.setObjectName("FieldLabel")
        layout.addWidget(type_label)
        type_row = QHBoxLayout()
        self.as_buyer = QRadioButton("Buy products")
        self.as_seller = QRadioButton("Buy and sell products")
        self.as_buyer.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.as_buyer)
        group.addButton(self.as_seller)
        type_row.addWidget(self.as_buyer)
        type_row.addWidget(self.as_seller)
        type_row.addStretch(1)
        layout.addLayout(type_row)

        self.name = Field("Full name", max_length=80)
        self.email = Field("Email", placeholder="you@example.com", max_length=100)
        self.phone = Field("Phone (optional)", placeholder="+52 55 1234 5678", max_length=20)
        self.password = Field("Password", password=True, max_length=128,
                              placeholder="At least 8 characters, letters and numbers")
        self.confirm = Field("Confirm password", password=True, max_length=128)
        self.store_name = Field("Store name", max_length=60)
        self.store_description = Field("Store description (optional)", multiline=True)
        for field in (self.name, self.email, self.phone, self.password, self.confirm,
                      self.store_name, self.store_description):
            layout.addWidget(field)

        self.as_seller.toggled.connect(self._update_seller_fields)
        self._update_seller_fields()

        self.submit = QPushButton("Create account")
        self.submit.setObjectName("Primary")
        self.submit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.submit.clicked.connect(self._on_submit)
        layout.addSpacing(4)
        layout.addWidget(self.submit)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(QLabel("Already have an account?"))
        link = QPushButton("Sign in")
        link.setObjectName("Link")
        link.setCursor(Qt.CursorShape.PointingHandCursor)
        link.clicked.connect(self.go_login.emit)
        row.addWidget(link)
        row.addStretch(1)
        layout.addLayout(row)

        self.confirm.input.returnPressed.connect(self._on_submit)

        # Server field names -> widgets, to show server errors next to the right input.
        self._fields = {
            "name": self.name, "email": self.email, "phone": self.phone, "password": self.password,
            "store_name": self.store_name, "store_description": self.store_description,
        }

    # ------------------------------------------------------------ helpers

    def _update_seller_fields(self) -> None:
        seller = self.as_seller.isChecked()
        self.store_name.setVisible(seller)
        self.store_description.setVisible(seller)

    def _all_fields(self):
        return (*self._fields.values(), self.confirm)

    def reset(self) -> None:
        for field in self._all_fields():
            field.clear()
        self.as_buyer.setChecked(True)
        self.error.show_message(None)
        self._set_busy(False)
        self.name.input.setFocus()

    def _set_busy(self, busy: bool) -> None:
        self.submit.setEnabled(not busy)
        self.submit.setText("Creating account…" if busy else "Create account")
        for field in self._all_fields():
            field.input.setEnabled(not busy)
        self.as_buyer.setEnabled(not busy)
        self.as_seller.setEnabled(not busy)

    def _validate(self) -> bool:
        seller = self.as_seller.isChecked()
        errors = {
            "name": validation.name(self.name.text()),
            "email": validation.email(self.email.text()),
            "phone": validation.phone(self.phone.text()),
            "password": validation.password(self.password.text()),
            "store_name": validation.store_name(self.store_name.text()) if seller else None,
            "store_description": validation.store_description(self.store_description.text()) if seller else None,
        }
        for key, field in self._fields.items():
            field.set_error(errors[key])
        confirm_error = None
        if self.confirm.text() != self.password.text():
            confirm_error = "Passwords do not match."
        self.confirm.set_error(confirm_error)
        return not any(errors.values()) and confirm_error is None

    # ------------------------------------------------------------ actions

    def _on_submit(self) -> None:
        if not self.submit.isEnabled():
            return
        self.error.show_message(None)
        if not self._validate():
            return

        seller = self.as_seller.isChecked()
        kwargs = dict(
            name=self.name.text().strip(),
            email=self.email.text().strip(),
            password=self.password.text(),
            account_type="seller" if seller else "buyer",
            phone=self.phone.text().strip() or None,
            store_name=self.store_name.text().strip() if seller else None,
            store_description=self.store_description.text().strip() if seller else None,
        )
        self._set_busy(True)
        run_in_background(lambda: self.api.register(**kwargs), self._on_success, self._on_error)

    def _on_success(self, _result) -> None:
        self._set_busy(False)
        self.password.clear()
        self.confirm.clear()
        self.registered.emit()

    def _on_error(self, err: ApiError) -> None:
        self._set_busy(False)
        field = self._fields.get(err.field or "")
        if field is not None:
            field.set_error(err.message)
            field.input.setFocus()
        else:
            self.error.show_message(err.message)
