from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

import validation
from api_client import ApiClient, ApiError
from ui.widgets import Field, MessageBox, centered_card
from ui.workers import run_in_background


class LoginView(QWidget):
    logged_in = Signal()
    go_register = Signal()

    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api
        layout = centered_card(self)

        title = QLabel("Marketplace")
        title.setObjectName("Title")
        subtitle = QLabel("Sign in to your account")
        subtitle.setObjectName("Subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(6)

        self.notice = MessageBox("notice")
        self.error = MessageBox("error")
        layout.addWidget(self.notice)
        layout.addWidget(self.error)

        self.email = Field("Email", placeholder="you@example.com", max_length=100)
        self.password = Field("Password", password=True, max_length=128)
        layout.addWidget(self.email)
        layout.addWidget(self.password)

        self.submit = QPushButton("Sign in")
        self.submit.setObjectName("Primary")
        self.submit.setDefault(True)
        self.submit.setCursor(Qt.CursorShape.PointingHandCursor)
        self.submit.clicked.connect(self._on_submit)
        layout.addSpacing(4)
        layout.addWidget(self.submit)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(QLabel("New here?"))
        link = QPushButton("Create an account")
        link.setObjectName("Link")
        link.setCursor(Qt.CursorShape.PointingHandCursor)
        link.clicked.connect(self.go_register.emit)
        row.addWidget(link)
        row.addStretch(1)
        layout.addLayout(row)

        self.email.input.returnPressed.connect(self.password.input.setFocus)
        self.password.input.returnPressed.connect(self._on_submit)

    # ------------------------------------------------------------ actions

    def reset(self, notice: str | None = None) -> None:
        self.password.clear()
        self.email.set_error(None)
        self.error.show_message(None)
        self.notice.show_message(notice)
        self._set_busy(False)
        (self.password if self.email.text() else self.email).input.setFocus()

    def _set_busy(self, busy: bool) -> None:
        self.submit.setEnabled(not busy)
        self.submit.setText("Signing in…" if busy else "Sign in")
        self.email.input.setEnabled(not busy)
        self.password.input.setEnabled(not busy)

    def _on_submit(self) -> None:
        if not self.submit.isEnabled():
            return
        self.error.show_message(None)
        self.notice.show_message(None)
        email = self.email.text().strip()
        password = self.password.text()

        email_error = validation.email(email)
        password_error = None if password else "Password is required."
        self.email.set_error(email_error)
        self.password.set_error(password_error)
        if email_error or password_error:
            return

        self._set_busy(True)
        run_in_background(lambda: self.api.login(email, password), self._on_success, self._on_error)

    def _on_success(self, _result) -> None:
        self._set_busy(False)
        self.password.clear()
        self.logged_in.emit()

    def _on_error(self, err: ApiError) -> None:
        self._set_busy(False)
        self.password.clear()  # never keep a rejected password in the field
        self.error.show_message(err.message)
        self.password.input.setFocus()
