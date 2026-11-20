"""Downloads product images in the background and caches them in memory."""

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QPixmap

from api_client import ApiClient
from ui.workers import run_in_background

_MAX_CACHE = 200


class ImageLoader(QObject):
    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._cache: dict[str, QPixmap] = {}

    def load(self, url: str | None, size: tuple[int, int], on_ready) -> None:
        """Call on_ready(pixmap) on the UI thread when the image is available."""
        if not url:
            return
        if url in self._cache:
            on_ready(self._scaled(self._cache[url], size))
            return

        def done(data: bytes):
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                if len(self._cache) >= _MAX_CACHE:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[url] = pixmap
                try:
                    on_ready(self._scaled(pixmap, size))
                except RuntimeError:
                    pass  # the widget was closed before the image arrived

        run_in_background(lambda: self.api.download_image(url), done, lambda _err: None)

    @staticmethod
    def _scaled(pixmap: QPixmap, size: tuple[int, int]) -> QPixmap:
        return pixmap.scaled(size[0], size[1], Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
