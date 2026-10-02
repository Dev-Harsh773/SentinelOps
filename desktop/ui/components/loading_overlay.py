"""Loading indicator overlay for non-blocking UI feedback."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


class LoadingOverlay(QWidget):
    """Subtle centered loading indicator with message."""

    def __init__(self, message: str = "Loading data...", parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.label = QLabel(message, self)
        self.label.setStyleSheet("color: #94A3B8; font-size: 14px; font-weight: 500;")
        layout.addWidget(self.label)

    def set_message(self, message: str) -> None:
        self.label.setText(message)
