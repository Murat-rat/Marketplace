"""Run API calls off the UI thread so the window never freezes.

Usage:
    run_in_background(lambda: api.login(email, pw), on_success, on_error)

Callbacks always run back on the UI thread (Qt queues the signal).
"""

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from api_client import ApiError


class _Signals(QObject):
    succeeded = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self):
        try:
            result = self.fn()
        except ApiError as err:
            self.signals.failed.emit(err)
        except Exception:  # never let a bug crash the app silently
            self.signals.failed.emit(ApiError(0, "client", "Unexpected error in the app. Try again."))
        else:
            self.signals.succeeded.emit(result)


_running: set[_Task] = set()  # keep tasks alive until they report back


def run_in_background(fn, on_success, on_error) -> None:
    task = _Task(fn)

    def done_ok(result):
        _running.discard(task)
        on_success(result)

    def done_err(err):
        _running.discard(task)
        on_error(err)

    task.signals.succeeded.connect(done_ok)
    task.signals.failed.connect(done_err)
    task.setAutoDelete(False)
    _running.add(task)
    QThreadPool.globalInstance().start(task)
