"""Color-coded status badge pills for severity, lifecycle, and operational health."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel


class StatusBadge(QLabel):
    """Visual pill displaying status or severity with standardized colors."""

    COLOR_MAP = {
        # Severity
        "critical": ("#991B1B", "#FCA5A5"),
        "high": ("#9A3412", "#FDBA74"),
        "medium": ("#854D0E", "#FDE047"),
        "low": ("#1E40AF", "#93C5FD"),
        "info": ("#334155", "#CBD5E1"),
        # Lifecycle
        "open": ("#854D0E", "#FEF08A"),
        "investigating": ("#1E40AF", "#BFDBFE"),
        "resolved": ("#166534", "#BBF7D0"),
        "closed": ("#334155", "#94A3B8"),
        # Operational
        "healthy": ("#166534", "#BBF7D0"),
        "degraded": ("#854D0E", "#FEF08A"),
        "errored": ("#991B1B", "#FCA5A5"),
        "unhealthy": ("#991B1B", "#FCA5A5"),
        "unknown": ("#334155", "#94A3B8"),
        "active": ("#166534", "#BBF7D0"),
        "disabled": ("#334155", "#94A3B8"),
        # Project
        "ready": ("#166534", "#BBF7D0"),
        "indexing": ("#1E40AF", "#BFDBFE"),
        "failed": ("#991B1B", "#FCA5A5"),
    }

    def __init__(self, text: str, category: str = "info", parent=None) -> None:
        super().__init__(text.upper(), parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_value(text, category)

    def set_value(self, text: str, category: str = "info") -> None:
        key = (category or text).lower()
        bg, fg = self.COLOR_MAP.get(key, ("#1E293B", "#94A3B8"))
        self.setText(text.upper())
        self.setStyleSheet(
            f"background-color: {bg}; color: {fg}; "
            f"border-radius: 4px; padding: 2px 8px; "
            f"font-weight: 700; font-size: 11px; letter-spacing: 0.5px;"
        )
