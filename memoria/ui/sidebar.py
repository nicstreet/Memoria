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
_ARROW_URL = f"url({_arrow_down_path()})"


class _Section(QWidget):
    """Sidebar section with a styled header and body."""

    def __init__(self, title: str, parent=None, first: bool = False):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(6)

        # Separator line above header — skip for the first section
        if not first:
            line = QFrame()
            line.setFrameShape(QFrame.Shape.HLine)
            line.setStyleSheet("color: #333;")
            layout.addWidget(line)

        hdr = QLabel(title)
        hdr.setStyleSheet(
            "color: #aaa; font-size: 12px; font-weight: 600; padding: 2px 0;"
        )
        layout.addWidget(hdr)

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
        self.setMinimumWidth(184)   # 12px margin + content + 12px margin, matches Clear button
        self.setMaximumWidth(320)

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
        self._build_people()
        self._build_tags()
        self._build_duplicates()
        self._layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

        # Clear all button pinned at bottom
        btn_container = QWidget()
        btn_container.setStyleSheet("background: transparent;")
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(12, 6, 12, 12)
        self._clear_btn = QPushButton("Clear all filters")
        self._clear_btn.clicked.connect(self.clear_all)
        self._clear_btn.setEnabled(False)
        btn_layout.addWidget(self._clear_btn)
        outer.addWidget(btn_container)

    # ── Section builders ─────────────────────────────────────────────────────

    def _build_search(self):
        sec = _Section("Search", first=True)
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
        sec = _Section("File Type")
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
        sec = _Section("Date Range")

        self._date_enabled = QCheckBox("Filter by date")
        self._date_enabled.setStyleSheet("color: #d4d4d4;")
        self._date_enabled.stateChanged.connect(self._on_date_enabled)
        self._date_enabled.stateChanged.connect(self._emit)
        sec.body().addWidget(self._date_enabled)

        date_style = f"""
            QDateEdit {{
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; color: #d4d4d4; padding: 2px 4px;
            }}
            QDateEdit:focus {{ border-color: #7c6af7; }}
            QDateEdit::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left: 1px solid #555;
            }}
            QDateEdit::down-arrow {{ image: {_ARROW_URL}; width: 20px; height: 12px; }}
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

        from_label = QLabel("From")
        from_label.setStyleSheet("color: #888; font-size: 11px;")
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDate(QDate(2000, 1, 1))
        self._date_from.setDisplayFormat("dd MMM yyyy")
        self._date_from.setStyleSheet(date_style)
        self._date_from.dateChanged.connect(self._emit)
        self._date_from.setEnabled(False)

        to_label = QLabel("To")
        to_label.setStyleSheet("color: #888; font-size: 11px;")
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(QDate.currentDate())
        self._date_to.setDisplayFormat("dd MMM yyyy")
        self._date_to.setStyleSheet(date_style)
        self._date_to.dateChanged.connect(self._emit)
        self._date_to.setEnabled(False)

        sec.body().addWidget(from_label)
        sec.body().addWidget(self._date_from)
        sec.body().addWidget(to_label)
        sec.body().addWidget(self._date_to)
        self._layout.addWidget(sec)

    def _build_location(self):
        self._location_section = _Section("Location")
        self._location_combo = QComboBox()
        self._location_combo.addItem("All locations", None)
        self._location_combo.setStyleSheet(f"""
            QComboBox {{
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; color: #d4d4d4; padding: 4px 8px;
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

    def _build_people(self):
        self._people_section = _Section("People")
        self._people_list = QListWidget()
        self._people_list.setFixedHeight(120)
        self._people_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._people_list.setStyleSheet(self._list_style())
        self._people_list.itemSelectionChanged.connect(self._emit)
        self._people_section.body().addWidget(self._people_list)
        self._layout.addWidget(self._people_section)
        self._people_section.setVisible(False)

    def _build_tags(self):
        self._tags_section = _Section("Tags")
        self._tags_list = QListWidget()
        self._tags_list.setFixedHeight(100)
        self._tags_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        self._tags_list.setStyleSheet(self._list_style())
        self._tags_list.itemSelectionChanged.connect(self._emit)
        self._tags_section.body().addWidget(self._tags_list)
        self._layout.addWidget(self._tags_section)
        self._tags_section.setVisible(False)

    def _build_duplicates(self):
        sec = _Section("Duplicates")
        self._dupes_check = QCheckBox("Show duplicates only")
        self._dupes_check.setStyleSheet("color: #d4d4d4;")
        self._dupes_check.stateChanged.connect(self._emit)
        sec.body().addWidget(self._dupes_check)
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
        self._people_section.setVisible(len(people) > 0)

        # Tags
        self._tags_list.clear()
        for tid, label, count in sorted(tags, key=lambda x: x[1]):
            item = QListWidgetItem(f"{label}  ({count})")
            item.setData(Qt.ItemDataRole.UserRole, tid)
            self._tags_list.addItem(item)
        self._tags_section.setVisible(len(tags) > 0)

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
            "duplicates_only": self._dupes_check.isChecked(),
        }

    def clear_all(self):
        self._search_input.clear()
        self._on_type_clicked("all")
        self._date_enabled.setChecked(False)
        self._location_combo.setCurrentIndex(0)
        self._people_list.clearSelection()
        self._tags_list.clearSelection()
        self._dupes_check.setChecked(False)
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
            }
            QListWidget::item { padding: 3px 6px; }
            QListWidget::item:selected { background: #5a4fd4; color: #fff; }
            QListWidget::item:hover:!selected { background: #3a3a3a; }
        """
