"""Marketplace desktop app.

Run from the project root:
    .venv\\Scripts\\python desktop\\main.py
"""

import sys
from pathlib import Path

# Allow running as "python desktop/main.py" from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import config  # noqa: E402
from api_client import ApiClient  # noqa: E402
from local_demo_api import LocalDemoApi  # noqa: E402
from session import Session  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.theme import STYLESHEET  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Marketplace")
    app.setStyle("Fusion")  # same look on every Windows version
    app.setStyleSheet(STYLESHEET)

    session = Session()
    if config.local_demo_enabled():
        api = LocalDemoApi(session)
        title = "Marketplace — Local demo (temporary data)"
    else:
        try:
            base_url = config.api_url()
        except RuntimeError as err:
            QMessageBox.critical(None, "Marketplace - configuration", str(err))
            return 1
        api = ApiClient(base_url, session)
        title = "Marketplace"

    window = MainWindow(api)
    window.setWindowTitle(title)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
