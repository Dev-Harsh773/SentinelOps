"""Transient non-modal toast notifications."""

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QLabel, QWidget


class ToastNotification(QWidget):
    """Floating non-modal notice in lower right corner."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.SubWindow | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.label = QLabel("", self)
        self.label.setStyleSheet(
            "background-color: #1E293B; color: #F8FAFC; border: 1px solid #3B82F6; "
            "border-radius: 6px; padding: 10px 16px; font-weight: 600; font-size: 13px;"
        )
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, text: str, is_error: bool = False, duration_ms: int = 3000) -> None:
        border = "#EF4444" if is_error else "#3B82F6"
        self.label.setStyleSheet(
            f"background-color: #1E293B; color: #F8FAFC; border: 1px solid {border}; "
            f"border-radius: 6px; padding: 10px 16px; font-weight: 600; font-size: 13px;"
        )
        self.label.setText(text)
        self.label.adjustSize()
        self.adjustSize()

        if self.parent():
            parent_rect = self.parent().rect()
            x = parent_rect.width() - self.width() - 20
            y = parent_rect.height() - self.height() - 20
            self.move(max(0, x), max(0, y))

        self.show()
        self.timer.start(duration_ms)
