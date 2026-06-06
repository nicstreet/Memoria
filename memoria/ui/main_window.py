from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QSlider, QSplitter, QVBoxLayout, QWidget,
)

from memoria.database.db import get_session
from memoria.database.models import Duplicate, File, FilePeople, FileTag, Metadata, Person, Tag
from memoria.ui.detail_panel import DetailPanel
from memoria.ui.grid_view import PhotoGridModel, PhotoGridView
from memoria.ui.sidebar import SidebarFilters
from memoria.ui.styles import DARK_STYLE
from memoria.ui.thumbnail_cache import ThumbnailCache
from memoria.ui.settings_store import load as load_settings, save as save_settings

log = logging.getLogger(__name__)


class _DbLoader(QObject):
    """Loads all data needed for the grid and sidebar from DB in a background thread."""
    finished = pyqtSignal(list, list, list, list)  # records, locations, people, tags

    def run(self):
        session = get_session()
        try:
            # Main file records
            rows = (
                session.query(
                    File.id, File.filepath, File.filename,
                    File.file_type, Metadata.date_taken,
                    Metadata.location_label, Metadata.gps_lat, Metadata.gps_lon,
                )
                .outerjoin(Metadata, Metadata.file_id == File.id)
                .order_by(Metadata.date_taken.desc().nullslast(), File.filename)
                .all()
            )
            records = [
                {
                    "id":             r.id,
                    "filepath":       r.filepath,
                    "filename":       r.filename,
                    "file_type":      r.file_type,
                    "date_taken":     r.date_taken,
                    "location_label": r.location_label,
                    "gps_lat":        r.gps_lat,
                    "gps_lon":        r.gps_lon,
                }
                for r in rows
            ]

            # Distinct locations
            locations = [
                r.location_label for r in
                session.query(Metadata.location_label)
                .filter(Metadata.location_label.isnot(None))
                .distinct().all()
            ]

            # People with face counts
            from sqlalchemy import func
            people = [
                (r.id, r.name, r.count) for r in
                session.query(Person.id, Person.name,
                              func.count(FilePeople.file_id).label("count"))
                .join(FilePeople, FilePeople.person_id == Person.id)
                .group_by(Person.id).all()
            ]

            # Tags with usage counts
            tags = [
                (r.id, r.label, r.count) for r in
                session.query(Tag.id, Tag.label,
                              func.count(FileTag.file_id).label("count"))
                .join(FileTag, FileTag.tag_id == Tag.id)
                .group_by(Tag.id).all()
            ]

            self.finished.emit(records, locations, people, tags)
        except Exception as e:
            log.error(f"Failed to load records: {e}", exc_info=True)
            self.finished.emit([], [], [], [])
        finally:
            session.close()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Memoria")
        self.resize(1400, 900)
        self.setMinimumSize(480, 360)
        self.setStyleSheet(DARK_STYLE)

        self._thumbnail_cache = ThumbnailCache(self)
        self._session = get_session()
        self._all_records: list[dict] = []
        ui_settings = load_settings()
        self._columns = ui_settings.get("columns", 5)

        self._build_ui()
        self._build_menu()
        self._load_records()
        # Defer column width until window is fully painted and laid out
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(200, self._apply_column_width)

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # Left sidebar
        self._sidebar = SidebarFilters()
        self._sidebar.filters_changed.connect(self._apply_filters)

        # Centre grid
        self._grid_model = PhotoGridModel(self._thumbnail_cache)
        self._grid_view = PhotoGridView()
        self._grid_view.set_model(self._grid_model)
        self._grid_view.file_selected.connect(self._on_file_selected)

        # Right detail panel
        self._detail = DetailPanel(self._thumbnail_cache)
        self._detail.set_session(self._session)

        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._grid_view)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, False)   # sidebar cannot be collapsed to zero
        splitter.setCollapsible(2, False)   # detail panel cannot be collapsed to zero
        splitter.setSizes([220, 960, 220])  # both panels equal width on open

        self.setCentralWidget(splitter)

        self._status_label = QLabel("Loading…")
        self._status_label.setStyleSheet(
            "color:#9a9a9a; padding-left:4px; background: transparent;"
        )
        self.statusBar().addWidget(self._status_label)
        self._build_statusbar()

    def _build_statusbar(self):
        slider_widget = QWidget()
        slider_widget.setStyleSheet("background: transparent;")
        slider_widget.setFixedWidth(200)
        row = QHBoxLayout(slider_widget)
        row.setContentsMargins(0, 0, 8, 0)
        row.setSpacing(6)

        btn_style = "color:#aaa; font-size:18px; font-weight:bold; border:none; background:transparent; padding:0;"

        smaller = QPushButton("−")
        smaller.setFixedWidth(20)
        smaller.setFlat(True)
        smaller.setStyleSheet(btn_style)
        smaller.clicked.connect(lambda: self._set_columns(min(12, self._columns + 1)))
        row.addWidget(smaller)

        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        self._size_slider.setMinimum(3)    # 3 columns = large cards
        self._size_slider.setMaximum(12)  # 12 columns = small cards
        self._size_slider.setValue(self._columns)
        self._size_slider.setSingleStep(1)
        self._size_slider.setPageStep(1)
        self._size_slider.setFixedWidth(100)
        self._size_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #444; height: 4px; border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #aaa; width: 12px; height: 12px;
                border-radius: 6px; margin: -4px 0;
            }
            QSlider::handle:horizontal:hover { background: #fff; }
            QSlider::sub-page:horizontal { background: #7c6af7; border-radius: 2px; }
        """)
        # Slider left = fewer columns (larger cards), right = more columns (smaller cards)
        # slider value = columns directly, no inversion
        self._size_slider.valueChanged.connect(self._on_slider_changed)
        row.addWidget(self._size_slider)

        larger = QPushButton("+")
        larger.setFixedWidth(20)
        larger.setFlat(True)
        larger.setStyleSheet(btn_style)
        larger.clicked.connect(lambda: self._set_columns(max(3, self._columns - 1)))
        row.addWidget(larger)

        self.statusBar().addPermanentWidget(slider_widget)
        self.statusBar().setSizeGripEnabled(False)

    def _on_slider_changed(self, value: int):
        self._columns = value
        self._update_card_width()

    def _set_columns(self, cols: int):
        cols = max(self._size_slider.minimum(), min(self._size_slider.maximum(), cols))
        if cols == self._columns:
            return
        self._columns = cols
        self._size_slider.blockSignals(True)
        self._size_slider.setValue(cols)
        self._size_slider.blockSignals(False)
        self._update_card_width()

    def _update_card_width(self):
        # Use widget width — stable reference unaffected by viewport margins
        full_width = self._grid_view.width()
        if full_width < 100:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self._update_card_width)
            return
        sb = self._grid_view.verticalScrollBar()
        sb_width = sb.width() if sb and sb.isVisible() else 8
        content_width = full_width - sb_width
        card_width = content_width // self._columns
        self._grid_view.set_card_width(card_width)

    def _apply_column_width(self):
        """Called on window resize — recalculates card width for current column count."""
        if not hasattr(self, '_size_slider'):
            return
        self._grid_view.setViewportMargins(0, 0, 0, 0)
        self._update_card_width()

    def _build_menu(self):
        menu_bar = self.menuBar()
        menu_bar.setStyleSheet(
            "QMenuBar { background:#252526; color:#d4d4d4; }"
            "QMenuBar::item:selected { background:#37373d; }"
            "QMenu { background:#252526; color:#d4d4d4; border:1px solid #444; min-width:220px; }"
            "QMenu::item { padding:4px 24px 4px 12px; }"
            "QMenu::item:selected { background:#5a4fd4; }"
            "QMenu::separator { height:1px; background:#444; margin:4px 0; }"
        )

        lib_menu = menu_bar.addMenu("Library")

        index_action = QAction("Re-index folders", self)
        index_action.setShortcut("Ctrl+R")
        index_action.triggered.connect(self._run_index)
        lib_menu.addAction(index_action)

        lib_menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(QApplication.quit)
        lib_menu.addAction(quit_action)

    # ── Data loading ─────────────────────────────────────────────────────────

    def _load_records(self):
        self._loader_thread = QThread()
        self._loader = _DbLoader()
        self._loader.moveToThread(self._loader_thread)
        self._loader_thread.started.connect(self._loader.run)
        self._loader.finished.connect(self._on_records_loaded)
        self._loader.finished.connect(self._loader_thread.quit)
        self._loader_thread.start()

    def _on_records_loaded(self, records: list[dict], locations: list[str],
                           people: list[tuple], tags: list[tuple]):
        self._all_records = records
        self._sidebar.populate(locations, people, tags)
        self._apply_filters(self._sidebar.current_filters())

    # ── Filtering ─────────────────────────────────────────────────────────────

    def _apply_filters(self, filters: dict):
        # Build set of duplicate file IDs if needed
        dupe_ids: set[int] | None = None
        if filters["duplicates_only"]:
            session = get_session()
            try:
                pairs = session.query(Duplicate.file_id_a, Duplicate.file_id_b).all()
                dupe_ids = set()
                for a, b in pairs:
                    dupe_ids.add(a)
                    dupe_ids.add(b)
            finally:
                session.close()

        # Build set of file IDs matching people filter
        people_ids: set[int] | None = None
        if filters["people"]:
            session = get_session()
            try:
                rows = (
                    session.query(FilePeople.file_id)
                    .filter(FilePeople.person_id.in_(filters["people"]))
                    .all()
                )
                people_ids = {r.file_id for r in rows}
            finally:
                session.close()

        # Build set of file IDs matching tags filter
        tag_ids: set[int] | None = None
        if filters["tags"]:
            session = get_session()
            try:
                rows = (
                    session.query(FileTag.file_id)
                    .filter(FileTag.tag_id.in_(filters["tags"]))
                    .all()
                )
                tag_ids = {r.file_id for r in rows}
            finally:
                session.close()

        filtered = []
        search = filters["search"].lower()

        for r in self._all_records:
            # Search
            if search and search not in r["filename"].lower():
                continue

            # File type
            if filters["file_type"] != "all" and r["file_type"] != filters["file_type"]:
                continue

            # Date range
            if filters["date_from"] and r["date_taken"]:
                if r["date_taken"] < filters["date_from"]:
                    continue
            if filters["date_to"] and r["date_taken"]:
                if r["date_taken"] > filters["date_to"]:
                    continue

            # Location
            if filters["location"] and r.get("location_label") != filters["location"]:
                continue

            # People
            if people_ids is not None and r["id"] not in people_ids:
                continue

            # Tags
            if tag_ids is not None and r["id"] not in tag_ids:
                continue

            # Duplicates
            if dupe_ids is not None and r["id"] not in dupe_ids:
                continue

            filtered.append(r)

        self._grid_model.load_records(filtered)
        total = len(self._all_records)
        shown = len(filtered)
        if shown == total:
            self._status_label.setText(f"{total:,} item{'s' if total != 1 else ''}")
        else:
            self._status_label.setText(
                f"{shown:,} of {total:,} item{'s' if total != 1 else ''}"
            )

    # ── Event handlers ───────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "_resize_timer"):
            from PyQt6.QtCore import QTimer
            self._resize_timer = QTimer()
            self._resize_timer.setSingleShot(True)
            self._resize_timer.timeout.connect(self._apply_column_width)
        self._resize_timer.start(50)  # wait 50ms after resize stops

    def _on_file_selected(self, record: dict):
        meta = None
        try:
            row = (
                self._session.query(Metadata)
                .filter(Metadata.file_id == record["id"])
                .first()
            )
            if row:
                meta = {
                    "date_taken":       row.date_taken,
                    "camera_make":      row.camera_make,
                    "camera_model":     row.camera_model,
                    "width":            row.width,
                    "height":           row.height,
                    "duration_seconds": row.duration_seconds,
                    "location_label":   row.location_label,
                    "gps_lat":          row.gps_lat,
                    "gps_lon":          row.gps_lon,
                }
                record["date_taken"] = row.date_taken
        except Exception as e:
            log.warning(f"Could not load metadata for file {record['id']}: {e}")
        self._detail.show_file(record, meta)

    def _run_index(self):
        from memoria.indexer.scanner import run_index
        self._status_label.setText("Indexing…")
        session = get_session()
        try:
            run_index(session)
        finally:
            session.close()
        self._load_records()

    def closeEvent(self, event):
        save_settings({"columns": self._columns})
        self._session.close()
        super().closeEvent(event)
