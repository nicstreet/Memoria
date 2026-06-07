def get_dark_style() -> str:
    from memoria.ui.theme import accent, accent_hover, accent_dim
    a      = accent()        # e.g. #7c6af7
    a_hov  = accent_hover()  # lighter
    a_dim  = accent_dim()    # darker / selection bg

    return f"""
/* ── Base ── */
QMainWindow, QDialog, QWidget {{
    background-color: #1e1e1e;
    color: #d4d4d4;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}

/* ── Scroll areas ── */
QScrollArea {{ border: none; background: #1e1e1e; }}

QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 2px 2px 2px 0;
    border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: #444450;
    border-radius: 3px;
    min-height: 32px;
}}
QScrollBar::handle:vertical:hover   {{ background: {a}; }}
QScrollBar::handle:vertical:pressed {{ background: {a_hov}; }}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical       {{ height: 0; background: none; }}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical       {{ background: none; }}

QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
    margin: 0 0 2px 2px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: #444450;
    border-radius: 3px;
    min-width: 32px;
}}
QScrollBar::handle:horizontal:hover   {{ background: {a}; }}
QScrollBar::handle:horizontal:pressed {{ background: {a_hov}; }}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal       {{ width: 0; background: none; }}
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal       {{ background: none; }}

/* ── List / grid view ── */
QListView {{
    background-color: #1e1e1e;
    border: none;
    outline: none;
}}
QListView::item:selected {{ background: transparent; }}
QListView::item:hover    {{ background: transparent; }}

/* ── Sidebar ── */
#sidebar {{
    background-color: #252526;
    border-right: 1px solid #333;
}}

/* ── Detail panel ── */
#detailPanel {{
    background-color: #252526;
    border-left: 1px solid #333;
}}
#detailPanel QLabel {{ color: #d4d4d4; }}
#detailTitle {{
    font-size: 14px;
    font-weight: bold;
    color: #ffffff;
}}
#detailMeta {{
    color: #9a9a9a;
    font-size: 12px;
}}

/* ── Status bar ── */
QStatusBar {{
    background: #252526;
    color: #9a9a9a;
    font-size: 12px;
    border-top: 1px solid #333;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{
    background: transparent;
    color: #9a9a9a;
}}

/* ── Menu bar ── */
QMenuBar {{
    background: #252526;
    color: #d4d4d4;
}}
QMenuBar::item:selected {{ background: #37373d; }}
QMenu {{
    background: #252526;
    color: #d4d4d4;
    border: 1px solid #444;
}}
QMenu::item           {{ padding: 4px 24px 4px 6px; min-width: 200px; }}
QMenu::item:selected  {{ background: {a_dim}; }}
QMenu::icon           {{ padding-left: 6px; width: 14px; }}
QMenu::separator      {{ height: 1px; background: #444; margin: 4px 0; }}

/* ── Buttons ── */
QPushButton {{
    background-color: #3a3a3a;
    color: #d4d4d4;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 5px 12px;
}}
QPushButton:hover   {{ background-color: #4a4a4a; }}
QPushButton:pressed {{ background-color: #2a2a2a; }}
QPushButton#primaryBtn, QPushButton#primary {{
    background-color: {a};
    border-color: {a};
    color: #ffffff;
}}
QPushButton#primaryBtn:hover, QPushButton#primary:hover {{
    background-color: {a_hov};
}}

/* ── Input fields ── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background: #3a3a3a;
    border: 1px solid #555;
    border-radius: 4px;
    color: #d4d4d4;
    padding: 3px 6px;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {a};
}}

/* ── ComboBox ── */
QComboBox {{
    background: #3a3a3a;
    border: 1px solid #555;
    border-radius: 4px;
    color: #d4d4d4;
    padding: 4px 8px;
}}
QComboBox:focus {{ border-color: {a}; }}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background: #2d2d2d;
    color: #d4d4d4;
    selection-background-color: {a_dim};
    border: 1px solid #555;
}}

/* ── Checkboxes ── */
QCheckBox {{ color: #d4d4d4; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border-radius: 3px;
    border: 1px solid #555;
    background: #2a2a2a;
}}
QCheckBox::indicator:checked {{
    background: {a};
    border-color: {a};
}}

/* ── Slider ── */
QSlider::groove:horizontal {{
    background: #444; height: 4px; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: #aaa; width: 12px; height: 12px;
    border-radius: 6px; margin: -4px 0;
}}
QSlider::handle:horizontal:hover {{ background: #fff; }}
QSlider::sub-page:horizontal {{ background: {a}; border-radius: 2px; }}

/* ── Labels ── */
QLabel#sectionHeader {{
    color: #777;
    font-size: 11px;
    font-weight: bold;
    padding: 4px 0;
}}

/* ── Splitter ── */
QSplitter::handle {{ background: #333; width: 1px; height: 1px; }}

/* ── Custom title bar ── */
#topBar {{
    background: #252526;
    border-bottom: 1px solid #333;
}}
#topBar #embeddedMenuBar {{
    background: transparent;
    border: none;
    padding: 0;
    color: #d4d4d4;
}}
#topBar #embeddedMenuBar::item {{
    padding: 4px 10px;
    background: transparent;
    border-radius: 3px;
}}
#topBar #embeddedMenuBar::item:selected {{
    background: #37373d;
}}
#topBarBtn {{
    background: transparent;
    border: none;
    color: #aaa;
    padding: 0;
    border-radius: 0;
    font-size: 13px;
}}
#topBarBtn:hover {{ background: #3a3a3a; color: #fff; }}
#topBarBtn:pressed {{ background: #2a2a2a; }}
#topBarBtn::menu-indicator {{ width: 0; image: none; }}
#winBtn {{
    background: transparent;
    border: none;
    color: #d4d4d4;
    border-radius: 0;
    padding: 0;
}}
#winBtn:hover {{ background: #3a3a3a; }}
#winBtn:pressed {{ background: #555; }}
#winBtnClose {{
    background: transparent;
    border: none;
    color: #d4d4d4;
    border-radius: 0;
    padding: 0;
}}
#winBtnClose:hover {{ background: #c42b1c; color: #ffffff; }}
#winBtnClose:pressed {{ background: #e81123; color: #ffffff; }}

/* ── Grid toolbar (Select All / Select None) ── */
#gridToolbar {{
    background: #252526;
    border-bottom: 1px solid #2e2e2e;
}}

"""


# Backwards-compatible alias so existing imports still work
DARK_STYLE = get_dark_style()
