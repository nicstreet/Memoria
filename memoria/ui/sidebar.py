from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, QDate, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

log = logging.getLogger(__name__)

from memoria.ui.icons import arrow_down_path as _arrow_down_path


class _WrappingCheck(QWidget):
    """
    A checkbox whose label word-wraps when the panel is narrow.
    QCheckBox itself has no setWordWrap, so we pair a bare indicator
    with a clickable QLabel.
    """
    stateChanged = pyqtSignal(int)

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._cb = QCheckBox()
        self._cb.stateChanged.connect(self.stateChanged)
        row.addWidget(self._cb, alignment=Qt.AlignmentFlag.AlignTop)

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #d4d4d4; font-size: 12px;")
        lbl.mousePressEvent = lambda _: self._cb.toggle()
        lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(lbl, stretch=1)

    def isChecked(self) -> bool:
        return self._cb.isChecked()

    def setChecked(self, v: bool):
        self._cb.setChecked(v)

    def setToolTip(self, text: str):       # forward to widget
        self._cb.setToolTip(text)
        super().setToolTip(text)
_ARROW_URL = f"url({_arrow_down_path()})"


class _Section(QWidget):
    """Sidebar section with an icon + styled header and body."""

    def __init__(self, title: str, icon: str = "", parent=None, first: bool = False):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(6)

        if not first:
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setStyleSheet("color: #333;")
            layout.addWidget(line)

        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        hdr_row.setSpacing(5)

        if icon:
            from memoria.ui.fluent_icons import FONT_NAME
            from PyQt6.QtGui import QFont
            icon_lbl = QLabel(icon)
            icon_lbl.setFont(QFont(FONT_NAME, 11))
            icon_lbl.setStyleSheet("color: #aaa; background: transparent;")
            icon_lbl.setFixedWidth(16)
            hdr_row.addWidget(icon_lbl)

        hdr = QLabel(title)
        hdr.setStyleSheet(
            "color: #aaa; font-size: 12px; font-weight: 600; padding: 2px 0;"
        )
        hdr_row.addWidget(hdr, stretch=1)
        layout.addLayout(hdr_row)

        self._body = QWidget()
        self._body.setStyleSheet("background: transparent;")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(4)
        layout.addWidget(self._body)

    def body(self) -> QVBoxLayout:
        return self._body_layout


class SidebarFilters(QWidget):
    """
    Left-hand filter panel.
    Emits filters_changed(dict) whenever any control changes.
    """
    filters_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setMinimumWidth(160)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setViewportMargins(0, 0, 0, 0)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(12, 4, 12, 12)
        self._layout.setSpacing(0)

        self._build_search()
        self._build_file_type()
        self._build_date_range()
        self._build_location()
        self._build_people_and_tags()
        self._build_duplicates()
        self._build_unidentified()
        self._build_ai_metadata()
        self._layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

        # NOT + Clear all buttons pinned at bottom
        btn_container = QWidget()
        btn_container.setStyleSheet("background: transparent;")
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(12, 6, 12, 12)
        btn_layout.setSpacing(6)

        self._not_btn = QPushButton("NOT")
        self._not_btn.setCheckable(True)
        self._not_btn.setFixedWidth(44)
        self._not_btn.setToolTip("Invert filter — show photos that do NOT match the current filters")
        self._not_btn.setStyleSheet("""
            QPushButton {
                background:#3a3a3a; border:1px solid #555;
                border-radius:4px; color:#888;
                padding:3px 6px; font-size:11px; font-weight:600;
            }
            QPushButton:checked {
                background:#c0392b; border-color:#c0392b; color:#fff;
            }
            QPushButton:hover:!checked { background:#4a4a4a; }
        """)
        self._not_btn.toggled.connect(self._emit)
        btn_layout.addWidget(self._not_btn)

        self._clear_btn = QPushButton("Clear all filters")
        self._clear_btn.clicked.connect(self.clear_all)
        self._clear_btn.setEnabled(False)
        btn_layout.addWidget(self._clear_btn, stretch=1)
        outer.addWidget(btn_container)

    # ── Section builders ─────────────────────────────────────────────────────

    def _build_search(self):
        from memoria.ui.fluent_icons import fi
        sec = _Section("Search", icon=fi.SEARCH, first=True)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Filename…")
        self._search_input.setStyleSheet("""
            QLineEdit {
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; color: #d4d4d4; padding: 4px 8px;
            }
            QLineEdit:focus { border-color: #7c6af7; }
        """)
        self._search_input.textChanged.connect(self._emit)
        sec.body().addWidget(self._search_input)
        self._layout.addWidget(sec)

    def _build_file_type(self):
        from memoria.ui.fluent_icons import fi
        sec = _Section("File Type", icon=fi.PHOTO)
        row = QHBoxLayout()
        row.setSpacing(4)
        self._type_buttons: dict[str, QPushButton] = {}
        for key, label in (("all", "All"), ("photo", "Photos"), ("video", "Videos")):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.setSizePolicy(
                btn.sizePolicy().horizontalPolicy().Expanding,
                btn.sizePolicy().verticalPolicy().Fixed,
            )
            btn.setStyleSheet(self._toggle_style())
            btn.clicked.connect(lambda _, k=key: self._on_type_clicked(k))
            self._type_buttons[key] = btn
            row.addWidget(btn)
        row.setStretch(0, 1)
        row.setStretch(1, 1)
        row.setStretch(2, 1)
        sec.body().addLayout(row)
        self._layout.addWidget(sec)

    def _build_date_range(self):
        from memoria.ui.fluent_icons import fi
        sec = _Section("Date Range", icon=fi.CALENDAR)

        self._date_enabled = _WrappingCheck("Filter by date")
        self._date_enabled.stateChanged.connect(self._on_date_enabled)
        self._date_enabled.stateChanged.connect(self._emit)
        sec.body().addWidget(self._date_enabled)

        date_style = f"""
            QDateEdit {{
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; color: #d4d4d4;
                padding: 2px 2px; font-size: 11px;
            }}
            QDateEdit:focus {{ border-color: #7c6af7; }}
            QDateEdit::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 16px;
                border-left: 1px solid #555;
            }}
            QDateEdit::down-arrow {{ image: {_ARROW_URL}; width: 16px; height: 10px; }}
            QCalendarWidget {{ background: #2d2d2d; color: #d4d4d4; }}
            QCalendarWidget QToolButton {{
                background: #3a3a3a; color: #d4d4d4; border-radius: 3px;
            }}
            QCalendarWidget QToolButton:hover {{ background: #7c6af7; }}
            QCalendarWidget QAbstractItemView {{
                background: #2d2d2d; color: #d4d4d4;
                selection-background-color: #7c6af7;
            }}
            QCalendarWidget QAbstractItemView:disabled {{ color: #555; }}
        """
        lbl_style = "color: #888; font-size: 10px; background: transparent;"

        # From / To side-by-side
        date_row = QWidget()
        date_row.setStyleSheet("background: transparent;")
        dr = QHBoxLayout(date_row)
        dr.setContentsMargins(0, 0, 0, 0)
        dr.setSpacing(8)

        from_col = QWidget(); from_col.setStyleSheet("background: transparent;")
        fv = QVBoxLayout(from_col); fv.setContentsMargins(0, 0, 0, 0); fv.setSpacing(2)
        from_label = QLabel("From"); from_label.setStyleSheet(lbl_style)
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDate(QDate(2000, 1, 1))
        self._date_from.setDisplayFormat("dd/MM/yyyy")
        self._date_from.setStyleSheet(date_style)
        self._date_from.dateChanged.connect(self._emit)
        self._date_from.setEnabled(False)
        fv.addWidget(from_label)
        fv.addWidget(self._date_from)
        dr.addWidget(from_col, stretch=1)

        to_col = QWidget(); to_col.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(to_col); tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)
        to_label = QLabel("To"); to_label.setStyleSheet(lbl_style)
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(QDate.currentDate())
        self._date_to.setDisplayFormat("dd/MM/yyyy")
        self._date_to.setStyleSheet(date_style)
        self._date_to.dateChanged.connect(self._emit)
        self._date_to.setEnabled(False)
        tv.addWidget(to_label)
        tv.addWidget(self._date_to)
        dr.addWidget(to_col, stretch=1)

        sec.body().addWidget(date_row)
        self._layout.addWidget(sec)

    def _build_location(self):
        from memoria.ui.fluent_icons import fi
        self._location_section = _Section("Location", icon=fi.MAP_PIN)
        self._location_combo = QComboBox()
        self._location_combo.addItem("All locations", None)
        self._location_combo.setStyleSheet(f"""
            QComboBox {{
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; color: #d4d4d4; padding: 4px 8px; font-size: 12px;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left: 1px solid #555;
            }}
            QComboBox::down-arrow {{ image: {_ARROW_URL}; width: 20px; height: 12px; }}
            QComboBox QAbstractItemView {{
                background: #2d2d2d; color: #d4d4d4;
                selection-background-color: #5a4fd4;
                border: 1px solid #555;
            }}
        """)
        self._location_combo.currentIndexChanged.connect(self._emit)
        self._location_section.body().addWidget(self._location_combo)
        self._layout.addWidget(self._location_section)

    def _build_people_and_tags(self):
        from memoria.ui.fluent_icons import fi, FONT_NAME
        from PyQt6.QtGui import QFont

        # Combined section — single divider line, "People & Tags" heading
        self._people_tags_section = _Section("People & Tags", icon=fi.PERSON)

        lbl_style = "color:#888; font-size:10px; background:transparent;"
        pair = QWidget(); pair.setStyleSheet("background: transparent;")
        h = QHBoxLayout(pair)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)

        # ── People column ──────────────────────────────────────────────────
        p_col = QWidget(); p_col.setStyleSheet("background: transparent;")
        pv = QVBoxLayout(p_col); pv.setContentsMargins(0, 0, 0, 0); pv.setSpacing(2)

        p_hdr = QWidget(); p_hdr.setStyleSheet("background: transparent;")
        p_hdr_row = QHBoxLayout(p_hdr)
        p_hdr_row.setContentsMargins(0, 0, 0, 0); p_hdr_row.setSpacing(4)
        p_icon = QLabel(fi.PERSON); p_icon.setFont(QFont(FONT_NAME, 10))
        p_icon.setStyleSheet("color:#888; background:transparent;")
        p_lbl = QLabel("People"); p_lbl.setStyleSheet(lbl_style)
        p_hdr_row.addWidget(p_icon); p_hdr_row.addWidget(p_lbl); p_hdr_row.addStretch()
        pv.addWidget(p_hdr)

        self._people_list = QListWidget()
        self._people_list.setFixedHeight(100)
        self._people_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._people_list.setStyleSheet(self._list_style())
        self._people_list.itemSelectionChanged.connect(self._emit)
        pv.addWidget(self._people_list)
        h.addWidget(p_col, stretch=1)

        # ── Tags column ────────────────────────────────────────────────────
        t_col = QWidget(); t_col.setStyleSheet("background: transparent;")
        tv = QVBoxLayout(t_col); tv.setContentsMargins(0, 0, 0, 0); tv.setSpacing(2)

        t_hdr = QWidget(); t_hdr.setStyleSheet("background: transparent;")
        t_hdr_row = QHBoxLayout(t_hdr)
        t_hdr_row.setContentsMargins(0, 0, 0, 0); t_hdr_row.setSpacing(4)
        t_icon = QLabel(fi.TAG); t_icon.setFont(QFont(FONT_NAME, 10))
        t_icon.setStyleSheet("color:#888; background:transparent;")
        t_lbl = QLabel("Tags"); t_lbl.setStyleSheet(lbl_style)
        t_hdr_row.addWidget(t_icon); t_hdr_row.addWidget(t_lbl); t_hdr_row.addStretch()
        tv.addWidget(t_hdr)

        self._tags_list = QListWidget()
        self._tags_list.setFixedHeight(100)
        self._tags_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._tags_list.setStyleSheet(self._list_style())
        self._tags_list.itemSelectionChanged.connect(self._emit)
        tv.addWidget(self._tags_list)
        h.addWidget(t_col, stretch=1)

        self._people_tags_section.body().addWidget(pair)
        self._layout.addWidget(self._people_tags_section)
        self._people_tags_section.setVisible(False)

    def _build_duplicates(self):
        from memoria.ui.fluent_icons import fi
        sec = _Section("Duplicates", icon=fi.COPY_X)
        self._dupes_check = _WrappingCheck("Show duplicates only")
        self._dupes_check.stateChanged.connect(self._emit)
        sec.body().addWidget(self._dupes_check)
        self._layout.addWidget(sec)

    def _build_ai_metadata(self):
        from memoria.ui.fluent_icons import fi
        sec = _Section("AI Generated", icon=fi.SCAN)
        self._ai_title_check = _WrappingCheck("Has AI Title")
        self._ai_title_check.setToolTip("Show only photos where an AI-generated title has been applied")
        self._ai_title_check.stateChanged.connect(self._emit)
        sec.body().addWidget(self._ai_title_check)

        self._ai_subject_check = _WrappingCheck("Has AI Subject")
        self._ai_subject_check.setToolTip("Show only photos where an AI-generated subject has been applied")
        self._ai_subject_check.stateChanged.connect(self._emit)
        sec.body().addWidget(self._ai_subject_check)
        self._layout.addWidget(sec)

    def _build_unidentified(self):
        from memoria.ui.fluent_icons import fi
        sec = _Section("Faces", icon=fi.FACE)
        self._unidentified_check = _WrappingCheck("Unidentified faces only")
        self._unidentified_check.setToolTip(
            "Show only photos that contain at least one face that hasn't been named yet"
        )
        self._unidentified_check.stateChanged.connect(self._emit)
        sec.body().addWidget(self._unidentified_check)
        self._layout.addWidget(sec)

    # ── Population from DB ───────────────────────────────────────────────────

    def populate(self, locations: list[str], people: list[tuple[int, str, int]],
                 tags: list[tuple[int, str, int]]):
        # Locations
        self._location_combo.blockSignals(True)
        self._location_combo.clear()
        self._location_combo.addItem("All locations", None)
        for loc in sorted(set(locations)):
            if loc:
                self._location_combo.addItem(loc, loc)
        self._location_combo.blockSignals(False)

        # People
        self._people_list.clear()
        for pid, name, count in sorted(people, key=lambda x: x[1]):
            item = QListWidgetItem(f"{name}  ({count})")
            item.setData(Qt.ItemDataRole.UserRole, pid)
            self._people_list.addItem(item)

        # Tags
        self._tags_list.clear()
        for tid, label, count in sorted(tags, key=lambda x: x[1]):
            item = QListWidgetItem(f"{label}  ({count})")
            item.setData(Qt.ItemDataRole.UserRole, tid)
            self._tags_list.addItem(item)

        # Show combined section if either list has entries
        self._people_tags_section.setVisible(len(people) > 0 or len(tags) > 0)

    # ── Public API ───────────────────────────────────────────────────────────

    def current_filters(self) -> dict:
        date_from = None
        date_to = None
        if self._date_enabled.isChecked():
            qd = self._date_from.date()
            date_from = datetime(qd.year(), qd.month(), qd.day())
            qd = self._date_to.date()
            date_to = datetime(qd.year(), qd.month(), qd.day(), 23, 59, 59)

        active_type = next(
            (k for k, b in self._type_buttons.items() if b.isChecked()), "all"
        )
        people_ids = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self._people_list.selectedItems()
        ]
        tag_ids = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self._tags_list.selectedItems()
        ]

        return {
            "search":          self._search_input.text().strip(),
            "file_type":       active_type,
            "date_from":       date_from,
            "date_to":         date_to,
            "location":        self._location_combo.currentData(),
            "people":          people_ids,
            "tags":            tag_ids,
            "duplicates_only":    self._dupes_check.isChecked(),
            "unidentified_faces": self._unidentified_check.isChecked(),
            "ai_title":           self._ai_title_check.isChecked(),
            "ai_subject":         self._ai_subject_check.isChecked(),
            "invert":             self._not_btn.isChecked(),
        }

    def clear_all(self):
        self._search_input.clear()
        self._on_type_clicked("all")
        self._date_enabled.setChecked(False)
        self._location_combo.setCurrentIndex(0)
        self._people_list.clearSelection()
        self._tags_list.clearSelection()
        self._dupes_check.setChecked(False)
        self._unidentified_check.setChecked(False)
        self._ai_title_check.setChecked(False)
        self._ai_subject_check.setChecked(False)
        self._not_btn.setChecked(False)
        self._emit()

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _on_type_clicked(self, key: str):
        for k, btn in self._type_buttons.items():
            btn.setChecked(k == key)
        self._emit()

    def _on_date_enabled(self, state: int):
        enabled = bool(state)
        self._date_from.setEnabled(enabled)
        self._date_to.setEnabled(enabled)

    def _emit(self, *_):
        filters = self.current_filters()
        is_active = (
            bool(filters["search"])
            or filters["file_type"] != "all"
            or filters["date_from"] is not None
            or filters["location"] is not None
            or bool(filters["people"])
            or bool(filters["tags"])
            or filters["duplicates_only"]
            or filters["unidentified_faces"]
            or filters["ai_title"]
            or filters["ai_subject"]
            or filters["invert"]
        )
        self._clear_btn.setEnabled(is_active)
        self.filters_changed.emit(filters)

    def _toggle_style(self) -> str:
        return """
            QPushButton {
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; color: #888; padding: 3px 6px; font-size: 12px;
            }
            QPushButton:checked {
                background: #7c6af7; border-color: #7c6af7; color: #fff;
            }
            QPushButton:hover:!checked { background: #4a4a4a; }
        """

    def _list_style(self) -> str:
        return """
            QListWidget {
                background: #2a2a2a; border: 1px solid #444;
                border-radius: 4px; color: #d4d4d4;
                font-size: 12px;
            }
            QListWidget::item { padding: 1px 6px; min-height: 20px; max-height: 20px; }
            QListWidget::item:selected { background: #5a4fd4; color: #fff; }
            QListWidget::item:hover:!selected { background: #3a3a3a; }
        """
