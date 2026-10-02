"""Enterprise-grade dark theme stylesheet for SentinelOps Windows Control Center."""

DARK_THEME_QSS = """
/* Global Application Styles */
QWidget {
    background-color: #0F141C;
    color: #E2E8F0;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
    selection-background-color: #2563EB;
    selection-color: #FFFFFF;
}

/* Header Bar */
#HeaderBar {
    background-color: #171F2C;
    border-bottom: 1px solid #283548;
    min-height: 54px;
    max-height: 54px;
    padding: 0 16px;
}

#AppTitle {
    font-size: 16px;
    font-weight: 700;
    color: #60A5FA;
    letter-spacing: 0.5px;
}

/* Sidebar Navigation */
#SidebarRail {
    background-color: #131A26;
    border-right: 1px solid #243042;
    min-width: 200px;
    max-width: 200px;
}

#SidebarButton {
    background-color: transparent;
    border: none;
    border-radius: 6px;
    color: #94A3B8;
    text-align: left;
    padding: 10px 14px;
    font-size: 13px;
    font-weight: 500;
}

#SidebarButton:hover {
    background-color: #1E293B;
    color: #F8FAFC;
}

#SidebarButton:checked {
    background-color: #1E3A8A;
    color: #93C5FD;
    font-weight: 600;
}

/* Card Containers */
QFrame.Card {
    background-color: #171F2C;
    border: 1px solid #283548;
    border-radius: 8px;
    padding: 14px;
}

/* Tables */
QTableWidget {
    background-color: #171F2C;
    border: 1px solid #283548;
    border-radius: 6px;
    gridline-color: #1E293B;
}

QTableWidget::item {
    padding: 6px 10px;
    border-bottom: 1px solid #1E293B;
}

QTableWidget::item:selected {
    background-color: #1E3A8A;
    color: #FFFFFF;
}

QHeaderView::section {
    background-color: #131A26;
    color: #94A3B8;
    padding: 8px 10px;
    border: none;
    border-bottom: 2px solid #283548;
    font-weight: 600;
    font-size: 12px;
}

/* Buttons */
QPushButton {
    background-color: #2563EB;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #1D4ED8;
}

QPushButton:pressed {
    background-color: #1E40AF;
}

QPushButton:disabled {
    background-color: #1E293B;
    color: #64748B;
}

QPushButton.Secondary {
    background-color: #334155;
    color: #F1F5F9;
}

QPushButton.Secondary:hover {
    background-color: #475569;
}

QPushButton.Danger {
    background-color: #DC2626;
}

QPushButton.Danger:hover {
    background-color: #B91C1C;
}

/* Input Fields */
QLineEdit, QComboBox, QTextEdit {
    background-color: #131A26;
    border: 1px solid #334155;
    border-radius: 6px;
    color: #F8FAFC;
    padding: 6px 10px;
}

QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
    border: 1px solid #3B82F6;
}

/* Scrollbars */
QScrollBar:vertical {
    background-color: #0F141C;
    width: 8px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: #334155;
    border-radius: 4px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background-color: #475569;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* Offline Banner */
#OfflineBanner {
    background-color: #854D0E;
    color: #FEF08A;
    font-weight: 600;
    font-size: 12px;
    padding: 6px 12px;
    border-bottom: 1px solid #CA8A04;
}
"""
