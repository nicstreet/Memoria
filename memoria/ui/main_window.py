from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication, QLabel, QMainWindow, QSlider, QSplitter,
    QVBoxLayout, QWidget,
)

from memoria.database.db import get_session
from memoria.database.models import File, Metadata
from memoria.ui.detail_panel import DetailPanel
from memoria.ui.grid_view import PhotoGridModel, PhotoGridView
from memoria.ui.styles import DARK_STYLE
from memoria.ui.thumbnail_cache import ThumbnailCache

log = logging.getLogger(__name__)


class _DbLoader(QObject):
    """Loads file records from DB in a background thread."""
    finished = pyqtSignal(list)

    def run(self):
        session = get_session()
        try:
            rows = (
                session.query(
                    File.id, File.filepath, File.filename,
                    File.file_type, Metadata.date_taken,
                )
                .outerjoin(Metadata, Metadata.file_id == File.id)
                .order_by(Metadata.date_taken.desc().nullslast(), File.filename)
                .all()
            )
            records = [
                {
                    "id":        r.id,
                    "filepath":  r.filepath,
                    "filename":  r.filename,
                    "file_type": r.file_type,
                    "date_taken": r.date_taken,
                }
                for r in rows
            ]
            self.finished.emit(records)
        except Exception as e:
            log.error(f"Failed to load records: {e}", exc_info=True)
            self.finished.emit([])
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

        self._build_ui()
        self._build_menu()
        self._load_records()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)

        # Left sidebar placeholder
        self._sidebar = QWidget()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setMinimumWidth(160)
        self._sidebar.setMaximumWidth(280)
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 12)
        sidebar_layout.setSpacing(8)
        sidebar_label = QLabel("FILTERS")
        sidebar_label.setObjectName("sectionHeader")
        sidebar_layout.addWidget(sidebar_label)
        sidebar_layout.addWidget(QLabel("Coming in Phase 4b…"))
        sidebar_layout.addStretch()

        # Centre grid
        self._grid_model = PhotoGridModel(self._thumbnail_cache)
        self._grid_view = PhotoGridView()
        self._grid_view.set_model(self._grid_model)
        self._grid_view.file_selected.connect(self._on_file_selected)

        # Right detail panel
        self._detail = DetailPanel(self._thumbnail_cache)

        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._grid_view)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(1, 1)  # grid gets all extra space

        self.setCentralWidget(splitter)

        self._status_label = QLabel("Loading…")
        self._status_label.setStyleSheet("color:#9a9a9a; padding-left:4px; background: transparent;")
        self.statusBar().addWidget(self._status_label)
        self._build_statusbar()

    def _build_statusbar(self):
        slider_widget = QWidget()
        slider_widget.setStyleSheet("background: transparent;")
        slider_widget.setFixedWidth(200)
        from PyQt6.QtWidgets import QHBoxLayout
        row = QHBoxLayout(slider_widget)
        row.setContentsMargins(0, 0, 8, 0)
        row.setSpacing(6)

        smaller = QLabel("−")
        smaller.setFixedWidth(20)
        smaller.setAlignment(Qt.AlignmentFlag.AlignCenter)
        smaller.setStyleSheet("color:#888; font-size:16px; font-weight:bold;")
        row.addWidget(smaller)

        self._size_slider = QSlider(Qt.Orientation.Horizontal)
        self._size_slider.setMinimum(120)
        self._size_slider.setMaximum(400)
        self._size_slider.setValue(220)
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
        self._size_slider.valueChanged.connect(self._on_size_changed)
        row.addWidget(self._size_slider)

        larger = QLabel("+")
        larger.setFixedWidth(20)
        larger.setAlignment(Qt.AlignmentFlag.AlignCenter)
        larger.setStyleSheet("color:#888; font-size:16px; font-weight:bold;")
        row.addWidget(larger)

        self.statusBar().addPermanentWidget(slider_widget)
        self.statusBar().setSizeGripEnabled(False)

    def _on_size_changed(self, value: int):
        self._grid_view.set_card_width(value)

    def _build_menu(self):
        menu_bar = self.menuBar()
        menu_bar.setStyleSheet(
            "QMenuBar { background:#252526; color:#d4d4d4; }"
            "QMenuBar::item:selected { background:#37373d; }"
            "QMenu { background:#252526; color:#d4d4d4; border:1px solid #444; min-width:220px; }"
            "QMenu::item { padding:4px 24px 4px 12px; }"
            "QMenu::item:selected { background:#094771; }"
            "QMenu::separator { height:1px; background:#444; margin:4px 0; }"
        )

        # Library menu
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

    def _on_records_loaded(self, records: list[dict]):
        self._grid_model.load_records(records)
        count = len(records)
        self._status_label.setText(f"{count:,} item{'s' if count != 1 else ''}")

    # ── Event handlers ───────────────────────────────────────────────────────

    def _on_file_selected(self, record: dict):
        # Fetch full metadata from DB
        meta = None
        try:
            row = (
                self._session.query(Metadata)
                .filter(Metadata.file_id == record["id"])
                .first()
            )
            if row:
                meta = {
                    "date_taken":      row.date_taken,
                    "camera_make":     row.camera_make,
                    "camera_model":    row.camera_model,
                    "width":           row.width,
                    "height":          row.height,
                    "duration_seconds": row.duration_seconds,
                    "location_label":  row.location_label,
                    "gps_lat":         row.gps_lat,
                    "gps_lon":         row.gps_lon,
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
        self._session.close()
        super().closeEvent(event)
