"""Left vertical navigation rail component."""

from typing import Callable, List
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop.state.signals import app_signals


class SidebarRail(QWidget):
    """Vertical navigation rail switching views in the main stacked container."""

    navigation_requested = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SidebarRail")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 16)
        layout.setSpacing(6)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        self.nav_items = [
            ("📊 Overview", 0),
            ("🚨 Incidents", 1),
            ("🔔 Feed", 2),
            ("🔌 Connectors", 3),
            ("📚 Knowledge", 4),
            ("⚙️ Settings", 5),
        ]

        self.buttons: List[QPushButton] = []
        for text, index in self.nav_items:
            btn = QPushButton(text, self)
            btn.setObjectName("SidebarButton")
            btn.setCheckable(True)
            if index == 0:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, idx=index: self.navigation_requested.emit(idx))
            self.btn_group.addButton(btn, index)
            layout.addWidget(btn)
            self.buttons.append(btn)

        layout.addStretch()

        # Listen for batch unread count updates
        app_signals.batch_unread_count_updated.connect(self._on_batch_unread_updated)

    def set_active_index(self, index: int) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)

    def _on_batch_unread_updated(self, count: int) -> None:
        feed_btn = self.buttons[2]
        if count > 0:
            feed_btn.setText(f"🔔 Feed ({count} in batch)")
        else:
            feed_btn.setText("🔔 Feed")
