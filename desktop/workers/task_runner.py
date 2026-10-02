"""Thread-safe background task executor for user-initiated asynchronous actions."""

from typing import Any, Callable, Optional
from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal, pyqtSlot


class WorkerSignals(QObject):
    """Signals emitted by worker tasks."""

    finished = pyqtSignal(object)
    error = pyqtSignal(object)


class WorkerTask(QRunnable):
    """Encapsulates a synchronous function to execute in the thread pool."""

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as exc:
            self.signals.error.emit(exc)


class TaskRunner:
    """Manages background task execution on QThreadPool."""

    def __init__(self, max_threads: int = 4) -> None:
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(max_threads)

    def run(
        self,
        fn: Callable[..., Any],
        on_success: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Submit a callable to the thread pool with callback wiring."""
        task = WorkerTask(fn, *args, **kwargs)
        if on_success:
            task.signals.finished.connect(on_success)
        if on_error:
            task.signals.error.connect(on_error)
        self.pool.start(task)

    def stop(self, timeout_ms: int = 2000) -> bool:
        """Wait for active worker tasks to complete on shutdown."""
        return self.pool.waitForDone(timeout_ms)
