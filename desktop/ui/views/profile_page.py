"""Profile editor and non-functional payment-method preview."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from api_client import ApiClient, ApiError
from session import User
from ui.workers import run_in_background
import validation


class ProfilePage(QWidget):
    back_requested = Signal()
    email_updated = Signal(str)
    session_expired = Signal()

    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.setObjectName("Page")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        header = QHBoxLayout()
        back = QPushButton("← Back to marketplace")
        back.setObjectName("Link")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(self.back_requested.emit)
        header.addWidget(back)
        header.addStretch(1)
        outer.addLayout(header)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.hide()
        outer.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 12, 12)
        layout.setSpacing(14)

        title = QLabel("Your profile")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        subtitle = QLabel("Manage your sign-in details and preview payment methods.")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)

        # Email card
        email_card = QFrame()
        email_card.setObjectName("Card")
        email_layout = QVBoxLayout(email_card)
        email_layout.setContentsMargins(18, 16, 18, 16)
        email_layout.setSpacing(8)
        email_title = QLabel("Email address")
        email_title.setObjectName("SectionTitle")
        email_layout.addWidget(email_title)
        email_layout.addWidget(QLabel("Your email is used to sign in to your account."))
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("you@example.com")
        self.email_input.setMaxLength(100)
        email_layout.addWidget(self.email_input)
        self.email_error = QLabel()
        self.email_error.setObjectName("FieldError")
        self.email_error.hide()
        email_layout.addWidget(self.email_error)
        self.save_email = QPushButton("Save email")
        self.save_email.setObjectName("Primary")
        self.save_email.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_email.clicked.connect(self._save_email)
        email_layout.addWidget(self.save_email, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(email_card)

        # Password card
        password_card = QFrame()
        password_card.setObjectName("Card")
        password_layout = QVBoxLayout(password_card)
        password_layout.setContentsMargins(18, 16, 18, 16)
        password_layout.setSpacing(8)
        password_title = QLabel("Change password")
        password_title.setObjectName("SectionTitle")
        password_layout.addWidget(password_title)
        password_layout.addWidget(QLabel("Enter your current password and choose a new one."))
        self.current_password = self._password_input("Current password")
        self.new_password = self._password_input("New password")
        self.confirm_password = self._password_input("Confirm new password")
        password_layout.addWidget(self.current_password)
        password_layout.addWidget(self.new_password)
        password_layout.addWidget(self.confirm_password)
        password_help = QLabel("Use 8–128 characters, including at least one letter and one number.")
        password_help.setObjectName("Muted")
        password_layout.addWidget(password_help)
        self.password_error = QLabel()
        self.password_error.setObjectName("FieldError")
        self.password_error.setWordWrap(True)
        self.password_error.hide()
        password_layout.addWidget(self.password_error)
        self.save_password = QPushButton("Update password")
        self.save_password.setObjectName("Primary")
        self.save_password.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_password.clicked.connect(self._save_password)
        password_layout.addWidget(self.save_password, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(password_card)

        # Decorative mock only: never collect or store actual payment details.
        payment_card = QFrame()
        payment_card.setObjectName("Card")
        payment_layout = QVBoxLayout(payment_card)
        payment_layout.setContentsMargins(18, 16, 18, 16)
        payment_layout.setSpacing(10)
        payment_title = QLabel("Payment methods")
        payment_title.setObjectName("SectionTitle")
        payment_layout.addWidget(payment_title)
        payment_note = QLabel("Visual preview only. These sample cards are not connected to payments or saved data.")
        payment_note.setObjectName("Muted")
        payment_note.setWordWrap(True)
        payment_layout.addWidget(payment_note)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        cards.addWidget(self._payment_card("CREDIT", "VISA", "4242", "08/29", "#253b80"), 1)
        cards.addWidget(self._payment_card("DEBIT", "MASTERCARD", "1881", "11/28", "#3d4c67"), 1)
        payment_layout.addLayout(cards)
        self.add_payment = QPushButton("Add payment method")
        self.add_payment.setObjectName("Secondary")
        self.add_payment.setEnabled(False)
        self.add_payment.setToolTip("Payment methods are a non-functional preview")
        payment_layout.addWidget(self.add_payment, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(payment_card)
        layout.addStretch(1)

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

    @staticmethod
    def _password_input(placeholder: str) -> QLineEdit:
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setMaxLength(128)
        return field

    @staticmethod
    def _payment_card(kind: str, brand: str, last4: str, expiry: str, color: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("PaymentPreview")
        frame.setStyleSheet(f"QFrame#PaymentPreview {{ background: {color}; border-radius: 10px; }}")
        frame.setMinimumHeight(126)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        top = QHBoxLayout()
        label = QLabel(f"{kind} · {brand}")
        label.setObjectName("PaymentPreviewText")
        mark = QLabel("DEMO")
        mark.setObjectName("PaymentPreviewText")
        top.addWidget(label)
        top.addStretch(1)
        top.addWidget(mark)
        layout.addLayout(top)
        number = QLabel(f"••••  ••••  ••••  {last4}")
        number.setObjectName("PaymentPreviewNumber")
        number.setTextFormat(Qt.TextFormat.PlainText)
        layout.addStretch(1)
        layout.addWidget(number)
        details = QLabel(f"CARDHOLDER NAME                 {expiry}")
        details.setObjectName("PaymentPreviewText")
        layout.addWidget(details)
        return frame

    def load(self, user: User) -> None:
        self.email_input.setText(user.email)
        self.current_password.clear()
        self.new_password.clear()
        self.confirm_password.clear()
        self._set_status(None)
        self._set_error(self.email_error, None)
        self._set_error(self.password_error, None)

    def _save_email(self) -> None:
        email = self.email_input.text().strip()
        error = validation.email(email)
        if error:
            self._set_error(self.email_error, error)
            return
        self._set_error(self.email_error, None)
        self.save_email.setEnabled(False)
        self._set_status("Saving email…")
        run_in_background(
            lambda: self.api.change_email(email),
            self._email_saved,
            lambda err: self._email_failed(err),
        )

    def _email_saved(self, result: dict) -> None:
        self.save_email.setEnabled(True)
        email = str(result["email"])
        self.email_input.setText(email)
        self.api.session.update_email(email)
        self.email_updated.emit(email)
        self._set_status("Email address updated.", success=True)

    def _email_failed(self, err: ApiError) -> None:
        self.save_email.setEnabled(True)
        if err.session_expired:
            self.session_expired.emit()
            return
        if err.field == "email":
            self._set_error(self.email_error, err.message)
            self._set_status(None)
            return
        self._set_status(err.message, error=True)

    def _save_password(self) -> None:
        current = self.current_password.text()
        new = self.new_password.text()
        confirm = self.confirm_password.text()
        if not current:
            self._set_error(self.password_error, "Enter your current password.")
            return
        error = validation.password(new)
        if error:
            self._set_error(self.password_error, error)
            return
        if new != confirm:
            self._set_error(self.password_error, "The new passwords do not match.")
            return
        if current == new:
            self._set_error(self.password_error, "Choose a password different from your current password.")
            return

        self._set_error(self.password_error, None)
        self.save_password.setEnabled(False)
        self._set_status("Updating password…")
        run_in_background(
            lambda: self.api.change_password(current, new),
            self._password_saved,
            self._password_failed,
        )

    def _password_saved(self, _result: dict) -> None:
        self.save_password.setEnabled(True)
        self.current_password.clear()
        self.new_password.clear()
        self.confirm_password.clear()
        self._set_status("Password updated.", success=True)

    def _password_failed(self, err: ApiError) -> None:
        self.save_password.setEnabled(True)
        if err.session_expired:
            self.session_expired.emit()
            return
        self._set_status(None)
        self._set_error(self.password_error, err.message)

    def _set_status(self, message: str | None, success: bool = False, error: bool = False) -> None:
        object_name = "Notice" if success else "FormError" if error else "Muted"
        self.status.setObjectName(object_name)
        self.status.setText(message or "")
        self.status.setVisible(bool(message))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    @staticmethod
    def _set_error(label: QLabel, message: str | None) -> None:
        label.setText(message or "")
        label.setVisible(bool(message))
