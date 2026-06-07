"""
Options Dialog
──────────────
Left column: section list.
Right column: stacked pages, one per section.

Layout inspired by Obsidian settings:
  • Items grouped inside a dark rounded card
  • Name + description left-aligned, control right-aligned
  • Thin separator between rows within a group
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox, QColorDialog, QDialog, QDialogButtonBox,
    QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

# ── Shared layout helpers ─────────────────────────────────────────────────────

_GROUP_BG   = "#252526"
_PAGE_BG    = "#1e1e1e"
_TITLE_CSS  = "color:#e0e0e0; font-size:13px; font-weight:600; background:transparent;"
_DESC_CSS   = "color:#777; font-size:11px; background:transparent;"
_SEP_CSS    = "background:#333;"


class _SettingRow(QWidget):
    """
    One row inside a settings group:
      [  Title          ]  [ control ]
      [  Description    ]
    """
    def __init__(self, title: str, description: str,
                 control: QWidget, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(16)

        # Left: title + description stacked
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(_TITLE_CSS)
        text_col.addWidget(title_lbl)

        desc_lbl = QLabel(description)
        desc_lbl.setStyleSheet(_DESC_CSS)
        desc_lbl.setWordWrap(True)
        text_col.addWidget(desc_lbl)

        row.addLayout(text_col, stretch=1)

        # Right: control — vertically centred
        control.setParent(self)
        row.addWidget(control, alignment=Qt.AlignmentFlag.AlignVCenter)


class _SettingGroup(QWidget):
    """
    Dark rounded card that holds one or more _SettingRow widgets
    separated by thin lines.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            _SettingGroup, QWidget#settingGroup {{
                background: {_GROUP_BG};
                border-radius: 8px;
            }}
        """)
        self.setObjectName("settingGroup")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._rows: list[QWidget] = []

    def add_row(self, title: str, description: str, control: QWidget):
        if self._rows:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setFixedHeight(1)
            sep.setStyleSheet(f"background:{_SEP_CSS[12:-1]}; border:none;")
            self._layout.addWidget(sep)

        row = _SettingRow(title, description, control)
        self._layout.addWidget(row)
        self._rows.append(row)
        return row


def _page_layout() -> tuple[QWidget, QVBoxLayout]:
    """Return a page widget + its VBoxLayout ready for group cards."""
    w = QWidget()
    w.setStyleSheet(f"background:{_PAGE_BG};")
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(16)
    return w, v


def _section_header(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color:#aaa; font-size:11px; font-weight:600; "
                      "padding:0 0 4px 0; background:transparent;")
    return lbl


# ── Subject manager widget ────────────────────────────────────────────────────

class _SubjectManagerWidget(QWidget):
    """
    Two-panel editor for default subjects:
      Left  — category list
      Right — subjects for selected category + add/delete controls
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self.setMinimumHeight(200)
        self.setMaximumHeight(300)

        # Work on a deep copy so changes only persist on save()
        from memoria.ui.default_subjects import get_categories
        self._data: list[tuple[str, list[str]]] = [
            (cat, list(subs)) for cat, subs in get_categories()
        ]

        # Vertical layout: columns at top, controls at bottom
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── Two-column layout (equal width) ────────────────────────────────
        cols_widget = QWidget()
        cols_widget.setStyleSheet("background:transparent;")
        cols_h = QHBoxLayout(cols_widget)
        cols_h.setContentsMargins(0, 0, 0, 0)
        cols_h.setSpacing(8)

        # Left: category list
        left = QWidget()
        left.setStyleSheet(f"background:{_GROUP_BG}; border-radius:6px;")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 4, 0, 4)
        lv.setSpacing(0)

        self._cat_list = QListWidget()
        self._cat_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent; border: none; outline: none;
                font-size: 12px;
            }}
            QListWidget::item {{
                color: #d4d4d4; padding: 1px 10px;
                min-height: 20px; max-height: 20px;
            }}
            QListWidget::item:selected {{
                background: #37373d; color: #fff;
            }}
            QListWidget::item:hover:!selected {{ background: #2d2d2d; }}
        """)
        for cat, _ in self._data:
            self._cat_list.addItem(cat)
        self._cat_list.currentRowChanged.connect(self._on_cat_changed)
        lv.addWidget(self._cat_list)
        cols_h.addWidget(left, stretch=1)

        # Right: subject list (equal width to left column)
        right = QWidget()
        right.setStyleSheet(f"background:{_GROUP_BG}; border-radius:6px;")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 4, 0, 4)
        rv.setSpacing(0)

        self._subj_list = QListWidget()
        self._subj_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent; border: none; outline: none;
                font-size: 12px;
            }}
            QListWidget::item {{
                color: #d4d4d4; padding: 1px 10px;
                min-height: 20px; max-height: 20px;
            }}
            QListWidget::item:selected {{
                background: #37373d; color: #fff;
            }}
            QListWidget::item:hover:!selected {{ background: #2d2d2d; }}
        """)
        rv.addWidget(self._subj_list)
        cols_h.addWidget(right, stretch=1)

        layout.addWidget(cols_widget, stretch=1)

        # ── Controls below (input + buttons) ───────────────────────────────
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)
        ctrl_row.setContentsMargins(0, 0, 0, 0)

        self._new_input = QLineEdit()
        self._new_input.setPlaceholderText("New subject…")
        self._new_input.setFixedHeight(24)
        self._new_input.returnPressed.connect(self._add_subject)
        ctrl_row.addWidget(self._new_input, stretch=1)

        add_btn = QPushButton("Add")
        add_btn.setFixedSize(52, 24)
        add_btn.setStyleSheet(
            "QPushButton{background:#3a3a3a;color:#d4d4d4;border:1px solid #555;"
            "border-radius:4px;padding:2px 6px;font-size:11px;}"
            "QPushButton:hover{background:#4a4a4a;}"
        )
        add_btn.clicked.connect(self._add_subject)
        ctrl_row.addWidget(add_btn)

        del_btn = QPushButton("Delete")
        del_btn.setFixedSize(56, 24)
        del_btn.setStyleSheet(
            "QPushButton{background:#3a2020;color:#f38ba8;border:1px solid #5a3030;"
            "border-radius:4px;padding:2px 6px;font-size:11px;}"
            "QPushButton:hover{background:#5a2020;}"
        )
        del_btn.clicked.connect(self._delete_subject)
        ctrl_row.addWidget(del_btn)

        layout.addLayout(ctrl_row)

        # Select first category
        if self._cat_list.count():
            self._cat_list.setCurrentRow(0)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _current_cat_idx(self) -> int:
        return self._cat_list.currentRow()

    def _on_cat_changed(self, idx: int):
        self._subj_list.clear()
        if 0 <= idx < len(self._data):
            for s in self._data[idx][1]:
                self._subj_list.addItem(s)

    def _add_subject(self):
        text = self._new_input.text().strip()
        if not text:
            return
        idx = self._current_cat_idx()
        if idx < 0:
            return
        cat, subs = self._data[idx]
        if text in subs:
            return
        subs.append(text)
        self._data[idx] = (cat, subs)
        self._subj_list.addItem(text)
        self._new_input.clear()

    def _delete_subject(self):
        idx = self._current_cat_idx()
        sel = self._subj_list.currentRow()
        if idx < 0 or sel < 0:
            return
        subject = self._subj_list.item(sel).text()
        reply = QMessageBox.question(
            self, "Delete subject",
            f"Remove \"{subject}\" from this category?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        cat, subs = self._data[idx]
        subs.remove(subject)
        self._data[idx] = (cat, subs)
        self._subj_list.takeItem(sel)

    def save(self):
        """Persist changes to settings."""
        from memoria.ui.default_subjects import save_categories
        save_categories(self._data)


# ── Section pages ─────────────────────────────────────────────────────────────

class _GeneralPage(QWidget):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._s = settings

        page, v = _page_layout()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)

        v.addWidget(_section_header("General"))

        group = _SettingGroup()

        self._cols = QSpinBox()
        self._cols.setRange(3, 12)
        self._cols.setValue(settings.get("columns", 5))
        self._cols.setFixedWidth(72)
        group.add_row(
            "Default grid columns",
            "Number of columns shown in the photo grid when the app starts.",
            self._cols,
        )

        self._exts = QCheckBox()
        self._exts.setChecked(settings.get("show_extensions", True))
        group.add_row(
            "Show file extensions",
            "Display the file extension (e.g. .jpg) in each photo card label.",
            self._exts,
        )

        v.addWidget(group)
        v.addStretch()

    def apply(self, settings: dict):
        settings["columns"]         = self._cols.value()
        settings["show_extensions"] = self._exts.isChecked()


class _EditorPage(QWidget):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Scrollable area for all content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #1e1e1e; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer.addWidget(scroll)

        page, v = _page_layout()
        scroll.setWidget(page)

        v.addWidget(_section_header("Editor"))

        group = _SettingGroup()

        self._quality = QSpinBox()
        self._quality.setRange(60, 100)
        self._quality.setValue(settings.get("jpeg_quality", 100))
        self._quality.setSuffix(" %")
        self._quality.setFixedWidth(100)
        group.add_row(
            "JPEG save quality",
            "Compression quality used when saving rotated JPEG files. "
            "Higher values preserve more detail.",
            self._quality,
        )

        self._fmt = QLineEdit(settings.get("rename_format", "%y-%m-%d_%H-%M_{subject}"))
        self._fmt.setFixedWidth(200)
        self._fmt.setToolTip(
            "%y=year(2) %Y=year(4) %m=month %d=day %H=hour %M=minute {subject}"
        )
        group.add_row(
            "Auto-rename format",
            "Template for the filename when a photo is auto-renamed. "
            "Tokens: %y %m %d %H %M for date/time, {subject} for the photo subject.",
            self._fmt,
        )

        v.addWidget(group)

        # ── Subject manager ───────────────────────────────────────────────
        self._subj_mgr = _SubjectManagerWidget()
        subj_row = _SettingRow(
            "Default subjects",
            "Manage subject categories and values for the EXIF Subject field.",
            self._subj_mgr,
        )
        v.addWidget(subj_row)

    def apply(self, settings: dict):
        settings["jpeg_quality"]  = self._quality.value()
        settings["rename_format"] = self._fmt.text().strip()
        self._subj_mgr.save()


class _AppearancePage(QWidget):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._colour = settings.get("accent_colour", "#7c6af7")

        page, v = _page_layout()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)

        v.addWidget(_section_header("Appearance"))

        group = _SettingGroup()

        # Control: reset button + colour swatch
        ctrl = QWidget()
        ctrl.setStyleSheet("background:transparent;")
        ctrl_row = QHBoxLayout(ctrl)
        ctrl_row.setContentsMargins(0, 0, 0, 0)
        ctrl_row.setSpacing(6)

        from memoria.ui.fluent_icons import fi, make_icon
        self._reset_btn = QPushButton()
        self._reset_btn.setIcon(make_icon(fi.REFRESH, size=12, colour="#d4d4d4"))
        self._reset_btn.setFixedSize(28, 28)
        self._reset_btn.setToolTip("Reset to default purple")
        self._reset_btn.setStyleSheet(
            "QPushButton { background:#3a3a3a; border:1px solid #555; "
            "border-radius:4px; padding: 2px; }"
            "QPushButton:hover { background:#4a4a4a; }"
        )
        self._reset_btn.clicked.connect(self._reset_colour)
        ctrl_row.addWidget(self._reset_btn)

        self._swatch = QPushButton()
        self._swatch.setFixedSize(28, 28)
        self._swatch.setToolTip("Click to choose a colour")
        self._swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._swatch.clicked.connect(self._pick_colour)
        self._update_swatch()
        ctrl_row.addWidget(self._swatch)

        group.add_row(
            "Highlight colour",
            "Accent colour used for buttons, scrollbars, focus rings and "
            "selections throughout the app. Changes apply immediately.",
            ctrl,
        )

        v.addWidget(group)
        v.addStretch()

    def _pick_colour(self):
        col = QColorDialog.getColor(QColor(self._colour), self, "Choose highlight colour")
        if col.isValid():
            self._colour = col.name()
            self._update_swatch()
            self._live_apply()

    def _reset_colour(self):
        self._colour = "#7c6af7"
        self._update_swatch()
        self._live_apply()

    def _update_swatch(self):
        self._swatch.setStyleSheet(
            f"QPushButton {{ background:{self._colour}; border:1px solid #555; "
            f"border-radius:14px; }}"
            f"QPushButton:hover {{ border-color:#aaa; }}"
        )

    def _live_apply(self):
        from memoria.ui.theme import set_accent
        set_accent(self._colour)

    def apply(self, settings: dict):
        settings["accent_colour"] = self._colour
        self._live_apply()


class _HotkeysPage(QWidget):
    _SHORTCUTS = [
        ("Ctrl+R",        "Re-index folders",
         "Scan watched folders for new or changed photos and videos."),
        ("Ctrl+F",        "Name faces",
         "Open the face cluster naming dialog."),
        ("Ctrl+P",        "People",
         "Browse and manage named people and their face assignments."),
        ("Ctrl+B",        "Bulk edit",
         "Edit title, subject, location and tags for all currently displayed photos."),
        ("Ctrl+Shift+R",  "Re-assess",
         "Scan unprocessed photos, match faces to known people, and sync tags."),
        ("Ctrl+D",        "Review duplicates",
         "Step through detected duplicate pairs and keep or trash one."),
        ("Ctrl+,",        "Options",
         "Open this settings dialog."),
        ("Ctrl+Q",        "Quit",
         "Exit Memoria."),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        page, v = _page_layout()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)

        v.addWidget(_section_header("Keyboard Shortcuts"))

        group = _SettingGroup()
        for key, name, desc in self._SHORTCUTS:
            badge = QLabel(key)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedHeight(24)
            badge.setMinimumWidth(120)
            badge.setStyleSheet(
                "background:#2a2a2a; color:#d4d4d4; font-family:monospace; "
                "font-size:11px; border:1px solid #444; border-radius:3px; "
                "padding:0 8px;"
            )
            group.add_row(name, desc, badge)

        v.addWidget(group)

        note = QLabel("Keyboard shortcuts are not currently customisable.")
        note.setStyleSheet("color:#555; font-size:10px;")
        v.addWidget(note)

        v.addStretch()


# ── Main dialog ───────────────────────────────────────────────────────────────

class OptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Options")
        self.resize(700, 460)
        self.setMinimumSize(580, 380)

        from memoria.ui.settings_store import load
        self._settings = load()

        # Global spinbox styling — grey arrows matching left panel
        a = self._settings.get("accent_colour", "#7c6af7")
        self.setStyleSheet(f"""
            QSpinBox, QDoubleSpinBox {{
                background: #3a3a3a;
                border: 1px solid #555;
                border-radius: 4px;
                color: #d4d4d4;
                padding: 2px 4px;
            }}
            QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {a}; }}
            QSpinBox::up-button, QSpinBox::down-button,
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
                background: #252526;
                border: none;
                width: 18px;
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover,
            QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
                background: #333333;
            }}
        """)

        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left section list ─────────────────────────────────────────────
        self._section_list = QListWidget()
        self._section_list.setFixedWidth(150)
        a = self._settings.get("accent_colour", "#7c6af7")
        self._section_list.setStyleSheet(f"""
            QListWidget {{
                background: #252526;
                border: none;
                border-right: 1px solid #333;
                outline: none;
                padding: 4px 0;
                font-size: 12px;
            }}
            QListWidget::item {{
                color: #d4d4d4;
                padding: 1px 12px;
                min-height: 20px;
                max-height: 20px;
            }}
            QListWidget::item:selected {{
                background: #37373d;
                color: #ffffff;
                border-left: 3px solid {a};
                padding-left: 9px;
            }}
            QListWidget::item:hover:!selected {{ background: #2d2d2d; }}
        """)
        self._section_list.setFrameShape(QListWidget.Shape.NoFrame)

        for name in ("General", "Editor", "Appearance", "Hotkeys"):
            self._section_list.addItem(QListWidgetItem(name))
        self._section_list.setCurrentRow(0)
        self._section_list.currentRowChanged.connect(self._on_section_changed)
        root.addWidget(self._section_list)

        # ── Right stacked pages ───────────────────────────────────────────
        right = QWidget()
        right.setStyleSheet(f"background:{_PAGE_BG};")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(20, 20, 20, 16)
        right_layout.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background:transparent;")

        self._pages = [
            _GeneralPage(self._settings),
            _EditorPage(self._settings),
            _AppearancePage(self._settings),
            _HotkeysPage(),
        ]
        for page in self._pages:
            self._stack.addWidget(page)

        right_layout.addWidget(self._stack, stretch=1)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Apply
        )
        btns.accepted.connect(self._save_and_close)
        btns.rejected.connect(self.reject)
        btns.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        right_layout.addWidget(btns)

        root.addWidget(right, stretch=1)

    def _on_section_changed(self, idx: int):
        self._stack.setCurrentIndex(idx)

    def _apply(self):
        from memoria.ui.settings_store import save
        for page in self._pages:
            if hasattr(page, "apply"):
                page.apply(self._settings)
        save(self._settings)

    def _save_and_close(self):
        self._apply()
        self.accept()
