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
from session import Session  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.theme import STYLESHEET  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Marketplace")
    app.setStyle("Fusion")  # same look on every Windows version
    app.setStyleSheet(STYLESHEET)

    try:
        base_url = config.api_url()
    except RuntimeError as err:
        QMessageBox.critical(None, "Marketplace - configuration", str(err))
        return 1

    window = MainWindow(ApiClient(base_url, Session()))
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
