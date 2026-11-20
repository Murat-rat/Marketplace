from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMainWindow, QStackedWidget

from api_client import ApiClient
from ui.views.login_view import LoginView
from ui.views.register_view import RegisterView
from ui.views.shell_view import ShellView


class MainWindow(QMainWindow):
    def __init__(self, api: ApiClient):
        super().__init__()
        self.api = api
        self.setWindowTitle("Marketplace")
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.login = LoginView(api)
        self.register = RegisterView(api)
        self.home = ShellView(api)
        for view in (self.login, self.register, self.home):
            self.stack.addWidget(view)

        self.login.logged_in.connect(self._enter_app)
        self.login.go_register.connect(self._show_register)
        self.register.registered.connect(self._enter_app)
        self.register.go_login.connect(lambda: self._show_login())
        self.home.logout_requested.connect(self._logout)
        self.home.session_expired.connect(self._session_expired)

        # Send the user back to the login screen when the 1-hour token expires.
        self._expiry_timer = QTimer(self)
        self._expiry_timer.setInterval(15_000)
        self._expiry_timer.timeout.connect(self._check_session)

        self._show_login()

    def _show_login(self, notice: str | None = None) -> None:
        self._expiry_timer.stop()
        self.stack.setCurrentWidget(self.login)
        self.login.reset(notice)

    def _show_register(self) -> None:
        self.stack.setCurrentWidget(self.register)
        self.register.reset()

    def _enter_app(self) -> None:
        self.stack.setCurrentWidget(self.home)
        self.home.start(self.api.session.user)
        self._expiry_timer.start()

    def _logout(self) -> None:
        self.api.logout()
        self._show_login("You have been signed out.")

    def _session_expired(self) -> None:
        if self.stack.currentWidget() is self.login:
            return
        self.api.logout()
        self._show_login("Your session expired. Please sign in again.")

    def _check_session(self) -> None:
        if not self.api.session.active:
            self._session_expired()
