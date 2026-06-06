DARK_STYLE = """
/* ── Base ── */
QMainWindow, QDialog, QWidget {
    background-color: #1e1e1e;
    color: #d4d4d4;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}

/* ── Scroll areas ── */
QScrollArea { border: none; background: #1e1e1e; }
QScrollBar:vertical {
    background: #2a2a2a; width: 8px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #555; border-radius: 4px; min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #777; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QScrollBar:horizontal {
    background: #2a2a2a; height: 8px; margin: 0;
}
QScrollBar::handle:horizontal {
    background: #555; border-radius: 4px; min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background: #777; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ── List / grid view ── */
QListView {
    background-color: #1e1e1e;
    border: none;
    outline: none;
}
QListView::item:selected {
    background: transparent;
}
QListView::item:hover {
    background: transparent;
}

/* ── Sidebar ── */
#sidebar {
    background-color: #252526;
    border-right: 1px solid #333;
}

/* ── Detail panel ── */
#detailPanel {
    background-color: #252526;
    border-left: 1px solid #333;
}
#detailPanel QLabel { color: #d4d4d4; }
#detailTitle {
    font-size: 14px;
    font-weight: bold;
    color: #ffffff;
}
#detailMeta {
    color: #9a9a9a;
    font-size: 12px;
}

/* ── Status bar ── */
QStatusBar {
    background: #252526;
    color: #9a9a9a;
    font-size: 12px;
    border-top: 1px solid #333;
}
QStatusBar::item {
    border: none;
}
QStatusBar QLabel {
    background: transparent;
    color: #9a9a9a;
}

/* ── Buttons ── */
QPushButton {
    background-color: #3a3a3a;
    color: #d4d4d4;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 5px 12px;
}
QPushButton:hover { background-color: #4a4a4a; }
QPushButton:pressed { background-color: #2a2a2a; }
QPushButton#primaryBtn {
    background-color: #7c6af7;
    border-color: #7c6af7;
    color: #ffffff;
}
QPushButton#primaryBtn:hover { background-color: #9480ff; }

/* ── Labels ── */
QLabel#sectionHeader {
    color: #777;
    font-size: 11px;
    font-weight: bold;
    padding: 4px 0;
}

/* ── Splitter ── */
QSplitter::handle { background: #333; width: 1px; height: 1px; }
"""
