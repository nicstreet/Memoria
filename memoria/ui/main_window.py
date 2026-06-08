from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, QTimer, QPoint, pyqtSignal, QObject, QEvent
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QMenu,
    QPushButton, QSizeGrip, QSlider, QSplitter, QVBoxLayout, QWidget,
)

from memoria.database.db import get_session
from memoria.database.models import Duplicate, EditLog, File, FilePeople, FileTag, Metadata, Person, Tag
from memoria.ui.detail_panel import DetailPanel
from memoria.ui.grid_view import PhotoGridModel, PhotoGridView
from memoria.ui.sidebar import SidebarFilters
from memoria.ui.styles import get_dark_style
from memoria.ui.thumbnail_cache import ThumbnailCache
from memoria.ui.log_panel import LogPanel
from memoria.ui.settings_store import load as load_settings, save as save_settings

log = logging.getLogger(__name__)


# ── Custom title bar ──────────────────────────────────────────────────────────

class _TopBar(QWidget):
    """
    Frameless-window title bar.
    Left:   hamburger sidebar toggle
    Centre: embedded QMenuBar with File / Edit / Help menus
    Right:  Minimize / Maximize / Close chrome buttons

    The QMenuBar lives as a plain child widget so all QActions work normally.
    Mouse events on the empty stretch area drag the window.
    """
    sidebar_toggled = pyqtSignal()

    def __init__(self, main_window: QMainWindow, parent=None):
        super().__init__(parent)
        self._win = main_window
        self._drag_pos: QPoint | None = None

        self.setFixedHeight(38)
        self.setObjectName("topBar")

        from memoria.ui.fluent_icons import fi, FONT_NAME

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 0, 0)
        layout.setSpacing(0)

        icon_font = QFont(FONT_NAME, 13)

        # ── Sidebar toggle ────────────────────────────────────────────────
        self._sidebar_btn = QPushButton(fi.SIDEBAR)
        self._sidebar_btn.setFont(icon_font)
        self._sidebar_btn.setFixedSize(38, 38)
        self._sidebar_btn.setToolTip("Toggle sidebar")
        self._sidebar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sidebar_btn.setObjectName("topBarBtn")
        self._sidebar_btn.clicked.connect(self.sidebar_toggled)
        layout.addWidget(self._sidebar_btn)

        # ── Icon menu buttons (File / Edit / Help) ────────────────────────
        def _menu_btn(glyph: str, tip: str) -> QPushButton:
            btn = QPushButton(glyph)
            btn.setFont(icon_font)
            btn.setFixedSize(38, 38)
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setObjectName("topBarBtn")
            return btn

        self._file_btn = _menu_btn(fi.FOLDER, "File")
        self._edit_btn = _menu_btn(fi.EDIT,   "Edit")
        self._help_btn = _menu_btn(fi.HELP,   "Help")
        # fi.HELP can render in accent colour on some Segoe variants — force muted grey
        self._help_btn.setStyleSheet(
            "QPushButton { color:#aaa; background:transparent; border:none; }"
            "QPushButton:hover { background:rgba(255,255,255,0.07); }"
            "QPushButton:pressed { background:rgba(255,255,255,0.14); }"
            "QPushButton::menu-indicator { width:0; image:none; }"
        )
        layout.addWidget(self._file_btn)
        layout.addWidget(self._edit_btn)
        layout.addWidget(self._help_btn)

        # ── Draggable spacer ──────────────────────────────────────────────
        layout.addStretch(1)

        # ── Window chrome buttons ─────────────────────────────────────────
        # Use plain Unicode + Segoe UI so glyphs are consistent across
        # Segoe Fluent Icons vs MDL2 Assets (E921/E922 differ between them).
        chrome_font = QFont("Segoe UI", 10)

        self._min_btn = QPushButton("−")   # − minus sign
        self._min_btn.setFont(chrome_font)
        self._min_btn.setFixedSize(46, 38)
        self._min_btn.setObjectName("winBtn")
        self._min_btn.setToolTip("Minimize")
        self._min_btn.clicked.connect(main_window.showMinimized)
        layout.addWidget(self._min_btn)

        self._max_btn = QPushButton("□")   # □ white square
        self._max_btn.setFont(chrome_font)
        self._max_btn.setFixedSize(46, 38)
        self._max_btn.setObjectName("winBtn")
        self._max_btn.setToolTip("Maximize")
        self._max_btn.clicked.connect(self._toggle_max)
        layout.addWidget(self._max_btn)

        self._close_btn = QPushButton("✕")  # ✕ multiplication X
        self._close_btn.setFont(chrome_font)
        self._close_btn.setFixedSize(46, 38)
        self._close_btn.setObjectName("winBtnClose")
        self._close_btn.setToolTip("Close")
        self._close_btn.clicked.connect(main_window.close)
        layout.addWidget(self._close_btn)

    # ── Public helpers ────────────────────────────────────────────────────

    def update_max_icon(self):
        if self._win.isMaximized():
            self._max_btn.setText("⧉")   # ⧉ overlapping squares = restore
            self._max_btn.setToolTip("Restore")
        else:
            self._max_btn.setText("□")        # □ white square = maximize
            self._max_btn.setToolTip("Maximize")

    def set_sidebar_tooltip(self, sidebar_visible: bool):
        self._sidebar_btn.setToolTip(
            "Hide sidebar" if sidebar_visible else "Show sidebar"
        )

    # ── Drag to move window ───────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            )
            e.accept()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            if self._win.isMaximized():
                self._win.showNormal()
                # Re-anchor drag relative to restored window size
                self._drag_pos = QPoint(
                    self._win.width() // 2, self.height() // 2
                )
            self._win.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._toggle_max()

    def _toggle_max(self):
        if self._win.isMaximized():
            self._win.showNormal()
        else:
            self._win.showMaximized()


# ── Background workers ────────────────────────────────────────────────────────

class _DbLoader(QObject):
    """Loads all data needed for the grid and sidebar from DB in a background thread."""
    finished = pyqtSignal(list, list, list, list)  # records, locations, people, tags

    def run(self):
        session = get_session()
        try:
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

            locations = [
                r.location_label for r in
                session.query(Metadata.location_label)
                .filter(Metadata.location_label.isnot(None))
                .distinct().all()
            ]

            from sqlalchemy import func
            people = [
                (r.id, r.name, r.count) for r in
                session.query(Person.id, Person.name,
                              func.count(FilePeople.file_id).label("count"))
                .join(FilePeople, FilePeople.person_id == Person.id)
                .group_by(Person.id).all()
            ]

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


class _BackgroundReassessWorker(QObject):
    finished = pyqtSignal(dict)

    def run(self):
        session = get_session()
        try:
            from memoria.faces.clustering import run_reassess
            stats = run_reassess(session)
            self.finished.emit(stats)
        except Exception as e:
            log.error(f"Background reassess failed: {e}", exc_info=True)
            self.finished.emit({"error": str(e)})
        finally:
            session.close()


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Frameless window — custom title bar handles chrome
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setWindowTitle("Memoria")
        self.resize(1400, 900)
        self.setMinimumSize(640, 480)

        self._thumbnail_cache = ThumbnailCache(self)
        self._session = get_session()
        self._all_records: list[dict] = []
        ui_settings = load_settings()
        self._columns = ui_settings.get("columns", 5)

        from memoria.ui.theme import set_accent
        set_accent(ui_settings.get("accent_colour", "#7c6af7"))
        self.setStyleSheet(get_dark_style())

        self._build_ui()
        self._build_menu()
        self._load_records()
        QTimer.singleShot(200, self._on_resize_settled)

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        # ── Title bar ──────────────────────────────────────────────────
        self._top_bar = _TopBar(self)
        self._top_bar.sidebar_toggled.connect(self._toggle_sidebar)

        # ── Sidebar ────────────────────────────────────────────────────
        self._sidebar = SidebarFilters()
        self._sidebar.setMinimumWidth(240)
        self._sidebar.filters_changed.connect(self._apply_filters)

        # ── Grid view + toolbar ─────────────────────────────────────────
        self._grid_model = PhotoGridModel(self._thumbnail_cache)
        self._grid_view = PhotoGridView()
        self._grid_view.set_model(self._grid_model)
        self._grid_view.file_selected.connect(self._on_file_selected)
        self._grid_view.rotate_requested.connect(self._on_rotate_requested)
        self._grid_view.face_review_requested.connect(self._on_face_review_requested)
        self._grid_view.not_duplicate_requested.connect(self._on_not_duplicate_requested)
        self._grid_view.meta_field_changed.connect(self._on_meta_field_changed)

        grid_container = self._build_grid_container()

        # ── Detail panel ────────────────────────────────────────────────
        self._detail = DetailPanel(self._thumbnail_cache)
        self._detail.set_session(self._session)
        self._detail.setMinimumWidth(260)
        self._detail.tag_added.connect(self._on_tag_added)
        self._detail.tag_removed.connect(self._on_tag_removed)

        # ── Splitter ────────────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.addWidget(self._sidebar)
        splitter.addWidget(grid_container)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(2, False)
        self._splitter = splitter
        self._sidebar_visible = True

        # ── Window container (title bar + content) ──────────────────────
        container = QWidget()
        container.setObjectName("windowContainer")
        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._top_bar)
        root.addWidget(splitter, 1)
        self.setCentralWidget(container)

        # ── Status bar ──────────────────────────────────────────────────
        self._status_label = QLabel("Loading…")
        self._status_label.setStyleSheet(
            "color:#9a9a9a; padding-left:4px; background: transparent;"
        )
        self.statusBar().addWidget(self._status_label)

        self._bg_label = QLabel()
        self._bg_label.setStyleSheet(
            "color:#7c6af7; padding: 0 8px; background: transparent; font-size:12px;"
        )
        self._bg_label.hide()
        self.statusBar().addWidget(self._bg_label)

        self._build_statusbar()

        # ── Background reassess state ───────────────────────────────────
        self._bg_thread: QThread | None = None
        self._bg_pending = False
        self._spinner_frames = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
        self._spinner_idx = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(100)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        self._bg_clear_timer = QTimer(self)
        self._bg_clear_timer.setSingleShot(True)
        self._bg_clear_timer.setInterval(6000)
        self._bg_clear_timer.timeout.connect(self._bg_label.hide)

    def _build_grid_container(self) -> QWidget:
        """Wraps the photo grid with a toolbar strip and a collapsible activity log panel."""
        container = QWidget()
        container.setObjectName("gridContainer")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar.setObjectName("gridToolbar")
        toolbar.setFixedHeight(34)
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 4, 8, 4)
        tb_layout.setSpacing(6)

        btn_style = (
            "QPushButton { background:#2d2d2d; color:#c0c0c0; border:1px solid #3a3a3a; "
            "border-radius:3px; padding:2px 10px; font-size:12px; }"
            "QPushButton:hover { background:#3a3a3a; color:#fff; border-color:#555; }"
            "QPushButton:pressed { background:#252526; }"
        )

        sel_all = QPushButton("Select All")
        sel_all.setFixedHeight(24)
        sel_all.setStyleSheet(btn_style)
        sel_all.clicked.connect(self._grid_view.selectAll)
        tb_layout.addWidget(sel_all)

        sel_none = QPushButton("Select None")
        sel_none.setFixedHeight(24)
        sel_none.setStyleSheet(btn_style)
        sel_none.clicked.connect(self._grid_view.clearSelection)
        tb_layout.addWidget(sel_none)

        tb_layout.addStretch()

        # Activity log toggle button
        self._log_toggle_btn = QPushButton("Activity Log")
        self._log_toggle_btn.setFixedHeight(24)
        self._log_toggle_btn.setCheckable(True)
        self._log_toggle_btn.setStyleSheet(
            btn_style +
            "QPushButton:checked { background:#37373d; color:#fff; border-color:#7c6af7; }"
        )
        self._log_toggle_btn.clicked.connect(self._toggle_log_panel)
        tb_layout.addWidget(self._log_toggle_btn)

        layout.addWidget(toolbar)
        layout.addWidget(self._grid_view, 1)

        # Activity log panel — hidden by default
        self._log_panel = LogPanel()
        self._log_panel.hide()
        self._log_panel.closed.connect(self._hide_log_panel)
        self._log_panel.exif_write_requested.connect(
            lambda fp, t, s: self._write_title_subject_exif(fp, t, s)
        )
        self._log_panel.tags_write_requested.connect(self._write_tags_exif)
        layout.addWidget(self._log_panel)

        return container

    def _toggle_log_panel(self):
        if self._log_panel.isVisible():
            self._hide_log_panel()
        else:
            self._log_panel.refresh()
            self._log_panel.show()
            self._log_toggle_btn.setChecked(True)

    def _hide_log_panel(self):
        self._log_panel.hide()
        self._log_toggle_btn.setChecked(False)

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
        self._size_slider.setMinimum(3)
        self._size_slider.setMaximum(12)
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
        self._size_slider.valueChanged.connect(self._on_slider_changed)
        row.addWidget(self._size_slider)

        larger = QPushButton("+")
        larger.setFixedWidth(20)
        larger.setFlat(True)
        larger.setStyleSheet(btn_style)
        larger.clicked.connect(lambda: self._set_columns(max(3, self._columns - 1)))
        row.addWidget(larger)

        self.statusBar().addPermanentWidget(slider_widget)
        # QSizeGrip replaces the OS resize handle lost with FramelessWindowHint
        grip = QSizeGrip(self)
        grip.setFixedSize(16, 16)
        self.statusBar().addPermanentWidget(grip)
        self.statusBar().setSizeGripEnabled(False)

    def _build_menu(self):
        """Attach popup menus to the File / Edit / Help icon buttons."""
        from PyQt6.QtWidgets import QMenu
        from memoria.ui.fluent_icons import fi, make_icon

        def _attach(btn, menu: QMenu):
            """Pop the menu below the button on click."""
            btn.setMenu(menu)

        # ── File ─────────────────────────────────────────────────────────
        file_menu = QMenu(self)

        index_action = QAction(make_icon(fi.REFRESH), "Re-index folders", self)
        index_action.setShortcut("Ctrl+R")
        index_action.triggered.connect(self._run_index)
        file_menu.addAction(index_action)

        file_menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(QApplication.quit)
        file_menu.addAction(quit_action)
        _attach(self._top_bar._file_btn, file_menu)

        # ── Edit ─────────────────────────────────────────────────────────
        edit_menu = QMenu(self)

        bulk_action = QAction(make_icon(fi.MULTI_SELECT), "Bulk Edit displayed photos…", self)
        bulk_action.setShortcut("Ctrl+B")
        bulk_action.triggered.connect(self._open_bulk_edit)
        edit_menu.addAction(bulk_action)

        dupes_action = QAction(make_icon(fi.COPY_X), "Review Duplicates…", self)
        dupes_action.setShortcut("Ctrl+D")
        dupes_action.triggered.connect(self._open_duplicate_review)
        edit_menu.addAction(dupes_action)

        edit_menu.addSeparator()

        face_action = QAction(make_icon(fi.FACE), "Name Faces…", self)
        face_action.setShortcut("Ctrl+F")
        face_action.triggered.connect(self._open_face_naming)
        edit_menu.addAction(face_action)

        persons_action = QAction(make_icon(fi.PERSON), "People…", self)
        persons_action.setShortcut("Ctrl+P")
        persons_action.triggered.connect(self._open_persons)
        edit_menu.addAction(persons_action)

        generate_action = QAction(make_icon(fi.SCAN), "Generate Metadata (AI)…", self)
        generate_action.setShortcut("Ctrl+G")
        generate_action.triggered.connect(self._open_generate_metadata)
        edit_menu.addAction(generate_action)

        reassess_action = QAction(make_icon(fi.SCAN), "Re-assess photos for faces & names…", self)
        reassess_action.setShortcut("Ctrl+Shift+R")
        reassess_action.triggered.connect(self._open_reassess)
        edit_menu.addAction(reassess_action)

        edit_menu.addSeparator()

        options_action = QAction(make_icon(fi.SETTINGS), "Options…", self)
        options_action.setShortcut("Ctrl+,")
        options_action.triggered.connect(self._open_options)
        edit_menu.addAction(options_action)
        _attach(self._top_bar._edit_btn, edit_menu)

        # ── Help ─────────────────────────────────────────────────────────
        help_menu = QMenu(self)

        about_action = QAction(make_icon(fi.HELP), "About Memoria…", self)
        about_action.triggered.connect(self._open_about)
        help_menu.addAction(about_action)
        _attach(self._top_bar._help_btn, help_menu)

    # ── Window state ──────────────────────────────────────────────────────

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if hasattr(self, "_top_bar"):
                self._top_bar.update_max_icon()

    # nativeEvent-based edge resize removed — causes PyQt6 access violation on Windows.
    # Window resize is handled via QSizeGrip in the status bar (bottom-right corner).
    # Full edge-resize will be revisited in a later stage using a pure-Qt approach.

    # ── Panel sizing ──────────────────────────────────────────────────────

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
        full_width = self._grid_view.width()
        if full_width < 100:
            QTimer.singleShot(100, self._update_card_width)
            return
        sb = self._grid_view.verticalScrollBar()
        sb_width = sb.width() if sb and sb.isVisible() else 8
        content_width = full_width - sb_width
        card_width = content_width // self._columns
        self._grid_view.set_card_width(card_width)

    def _apply_column_width(self):
        if not hasattr(self, "_size_slider"):
            return
        self._grid_view.setViewportMargins(0, 0, 0, 0)
        self._update_card_width()

    def _set_panel_sizes(self):
        """Size side panels: sidebar min 240px, detail min 260px, centre gets the rest."""
        w = self.width()
        if w < 600:
            return
        sidebar = max(240, int(w * 0.19))
        detail  = max(260, int(w * 0.21))
        centre  = max(200, w - sidebar - detail)
        if self._sidebar_visible:
            self._splitter.setSizes([sidebar, centre, detail])
        else:
            self._splitter.setSizes([0, w - detail, detail])

    def _toggle_sidebar(self):
        self._sidebar_visible = not self._sidebar_visible
        self._set_panel_sizes()
        self._top_bar.set_sidebar_tooltip(self._sidebar_visible)

    # ── Data loading ──────────────────────────────────────────────────────

    def _load_records(self):
        self._loader_thread = QThread()
        self._loader = _DbLoader()
        self._loader.moveToThread(self._loader_thread)
        self._loader_thread.started.connect(self._loader.run)
        self._loader.finished.connect(self._on_records_loaded)
        self._loader.finished.connect(self._loader_thread.quit)
        self._loader_thread.start()

    def _on_records_loaded(self, records, locations, people, tags):
        self._all_records = records
        self._sidebar.populate(locations, people, tags)
        self._apply_filters(self._sidebar.current_filters())
        self._refresh_duplicate_ids()

    def _refresh_duplicate_ids(self):
        try:
            session = get_session()
            pairs = session.query(Duplicate.file_id_a, Duplicate.file_id_b)\
                           .filter(Duplicate.reviewed == False).all()
            session.close()
            dup_ids = {a for a, _ in pairs} | {b for _, b in pairs}
            self._grid_view.set_duplicate_ids(dup_ids)
        except Exception as e:
            log.warning(f"Could not load duplicate IDs: {e}")

    # ── Filtering ─────────────────────────────────────────────────────────

    def _apply_filters(self, filters: dict):
        dupe_ids: set[int] | None = None
        if filters["duplicates_only"]:
            session = get_session()
            try:
                pairs = session.query(Duplicate.file_id_a, Duplicate.file_id_b).all()
                dupe_ids = {a for a, _ in pairs} | {b for _, b in pairs}
            finally:
                session.close()

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

        unidentified_ids: set[int] | None = None
        if filters.get("unidentified_faces"):
            session = get_session()
            try:
                from memoria.database.models import FaceDetection
                rows = (
                    session.query(FaceDetection.file_id)
                    .filter(FaceDetection.person_id.is_(None),
                            FaceDetection.file_id.isnot(None))
                    .distinct().all()
                )
                unidentified_ids = {r.file_id for r in rows}
            finally:
                session.close()

        ai_title_ids: set[int] | None = None
        if filters.get("ai_title"):
            session = get_session()
            try:
                rows = (
                    session.query(EditLog.file_id)
                    .filter(EditLog.source == "ai",
                            EditLog.action_type == "title",
                            EditLog.file_id.isnot(None))
                    .distinct().all()
                )
                ai_title_ids = {r.file_id for r in rows}
            finally:
                session.close()

        ai_subject_ids: set[int] | None = None
        if filters.get("ai_subject"):
            session = get_session()
            try:
                rows = (
                    session.query(EditLog.file_id)
                    .filter(EditLog.source == "ai",
                            EditLog.action_type == "subject",
                            EditLog.file_id.isnot(None))
                    .distinct().all()
                )
                ai_subject_ids = {r.file_id for r in rows}
            finally:
                session.close()

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
            if search and search not in r["filename"].lower():
                continue
            if filters["file_type"] != "all" and r["file_type"] != filters["file_type"]:
                continue
            if filters["date_from"] and r["date_taken"]:
                if r["date_taken"] < filters["date_from"]:
                    continue
            if filters["date_to"] and r["date_taken"]:
                if r["date_taken"] > filters["date_to"]:
                    continue
            if filters["location"] and r.get("location_label") != filters["location"]:
                continue
            if people_ids is not None and r["id"] not in people_ids:
                continue
            if tag_ids is not None and r["id"] not in tag_ids:
                continue
            if unidentified_ids is not None and r["id"] not in unidentified_ids:
                continue
            if dupe_ids is not None and r["id"] not in dupe_ids:
                continue
            if ai_title_ids is not None and r["id"] not in ai_title_ids:
                continue
            if ai_subject_ids is not None and r["id"] not in ai_subject_ids:
                continue
            filtered.append(r)

        if filters.get("invert") and len(filtered) != len(self._all_records):
            filtered_ids = {r["id"] for r in filtered}
            filtered = [r for r in self._all_records if r["id"] not in filtered_ids]

        self._grid_model.load_records(filtered)
        total = len(self._all_records)
        shown = len(filtered)
        if shown == total:
            self._status_label.setText(f"{total:,} item{'s' if total != 1 else ''}")
        else:
            self._status_label.setText(
                f"{shown:,} of {total:,} item{'s' if total != 1 else ''}"
            )

    # ── Event handlers ────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "_resize_timer"):
            self._resize_timer = QTimer()
            self._resize_timer.setSingleShot(True)
            self._resize_timer.timeout.connect(self._on_resize_settled)
        self._resize_timer.start(50)

    def _on_resize_settled(self):
        self._set_panel_sizes()
        self._apply_column_width()

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
                    "title":            row.title,
                    "subject":          row.subject,
                }
                record["date_taken"] = row.date_taken
        except Exception as e:
            log.warning(f"Could not load metadata for file {record['id']}: {e}")
        self._detail.show_file(record, meta)

    def _on_rotate_requested(self, record: dict):
        from PIL import Image
        filepath = record["filepath"]
        file_id  = record["id"]
        try:
            with Image.open(filepath) as img:
                rotated = img.transpose(Image.Transpose.ROTATE_270)
                fmt = img.format or "JPEG"
                save_kwargs = {"quality": 95} if fmt.upper() in ("JPEG", "JPG") else {}
                rotated.save(filepath, format=fmt, **save_kwargs)

            from memoria.database.models import File, Metadata, FaceDetection
            file_row = self._session.query(File).get(file_id)
            if file_row:
                file_row.file_modified_at = datetime.utcnow()
                file_row.face_scanned_at  = None

            meta_row = self._session.query(Metadata).filter_by(file_id=file_id).first()
            if meta_row and meta_row.width and meta_row.height:
                meta_row.width, meta_row.height = meta_row.height, meta_row.width

            self._session.query(FaceDetection).filter_by(file_id=file_id).delete()
            self._session.commit()

            self._log_edit(
                file_id=file_id,
                filename=record["filename"],
                filepath=filepath,
                action_type="rotate",
                new_value="90° CW",
                source="user",
                saved=True,
            )

            self._thumbnail_cache.invalidate(file_id, filepath, record["file_type"])
            if (self._detail._current_record or {}).get("id") == file_id:
                self._on_file_selected(record)

        except Exception as e:
            log.error(f"Rotate failed for {filepath}: {e}")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Rotate failed", str(e))

    def _on_face_review_requested(self, record: dict):
        from memoria.ui.face_review import FaceReviewDialog
        full_record = dict(record)
        try:
            from memoria.database.models import Metadata
            meta_row = self._session.query(Metadata).filter_by(file_id=record["id"]).first()
            if meta_row and meta_row.date_taken:
                full_record["date_taken"] = meta_row.date_taken
        except Exception:
            pass
        dlg = FaceReviewDialog(self._session, full_record, parent=self)
        dlg.people_changed.connect(self._load_records)
        dlg.people_changed.connect(self.trigger_background_reassess)
        dlg.exec()
        if (self._detail._current_record or {}).get("id") == record["id"]:
            self._on_file_selected(full_record)

    def _on_meta_field_changed(self, file_id: int, field: str, value: str):
        from memoria.database.models import Metadata, File
        try:
            meta = self._session.query(Metadata).filter_by(file_id=file_id).first()
            old_val = getattr(meta, field, None) if meta else None
            if meta is None:
                meta = Metadata(file_id=file_id)
                self._session.add(meta)
            setattr(meta, field, value or None)

            file_row = self._session.query(File).get(file_id)
            self._session.commit()

            # Log the change
            self._log_edit(
                file_id=file_id,
                filename=file_row.filename if file_row else "",
                filepath=file_row.filepath if file_row else "",
                action_type=field,
                old_value=str(old_val) if old_val is not None else "",
                new_value=value or "",
                source="user",
                saved=False,
            )

            # Optionally auto-write EXIF immediately
            settings = load_settings()
            if settings.get("auto_write_exif", False):
                if file_row and file_row.file_type == "photo":
                    self._write_title_subject_exif(
                        file_row.filepath, meta.title, meta.subject
                    )
                    self._mark_log_saved(file_id, field)

            if (self._detail._current_record or {}).get("id") == file_id:
                if field == "title":
                    self._detail._title_input.setText(value)
                else:
                    self._detail._subject_input.setText(value)
                if self._detail._current_meta is not None:
                    self._detail._current_meta[field] = value or None
                self._detail._refresh_status()

            # Refresh log panel if visible
            if self._log_panel.isVisible():
                self._log_panel.refresh()

        except Exception as e:
            self._session.rollback()
            log.error(f"Could not save {field}: {e}")

    def _on_tag_added(self, file_id: int, label: str):
        """Called when a tag chip is added in the detail panel."""
        try:
            file_row = self._session.query(File).get(file_id)
            self._log_edit(
                file_id=file_id,
                filename=file_row.filename if file_row else "",
                filepath=file_row.filepath if file_row else "",
                action_type="tag_add",
                new_value=label,
                source="user",
                saved=load_settings().get("auto_write_exif", False),
            )
        except Exception as e:
            log.warning(f"Could not log tag_add: {e}")
        if self._log_panel.isVisible():
            self._log_panel.refresh()

    def _on_tag_removed(self, file_id: int, label: str):
        """Called when a tag chip is removed in the detail panel."""
        try:
            file_row = self._session.query(File).get(file_id)
            self._log_edit(
                file_id=file_id,
                filename=file_row.filename if file_row else "",
                filepath=file_row.filepath if file_row else "",
                action_type="tag_remove",
                old_value=label,
                source="user",
                saved=load_settings().get("auto_write_exif", False),
            )
        except Exception as e:
            log.warning(f"Could not log tag_remove: {e}")
        if self._log_panel.isVisible():
            self._log_panel.refresh()

    def _log_edit(
        self, *,
        file_id: int | None,
        filename: str,
        filepath: str,
        action_type: str,
        old_value: str = "",
        new_value: str = "",
        source: str = "user",
        saved: bool = False,
    ):
        """Insert one row into the edit_log table. Never raises."""
        try:
            session = get_session()
            try:
                entry = EditLog(
                    file_id=file_id,
                    filename=filename,
                    filepath=filepath,
                    action_type=action_type,
                    old_value=old_value or None,
                    new_value=new_value or None,
                    source=source,
                    saved=saved,
                )
                session.add(entry)
                session.commit()
            finally:
                session.close()
        except Exception as e:
            log.warning(f"Could not write edit log: {e}")

    def _mark_log_saved(self, file_id: int, action_type: str):
        """Mark the most-recent unsaved log entry for (file_id, action_type) as saved."""
        try:
            session = get_session()
            try:
                entry = (
                    session.query(EditLog)
                    .filter(
                        EditLog.file_id == file_id,
                        EditLog.action_type == action_type,
                        EditLog.saved == False,   # noqa: E712
                    )
                    .order_by(EditLog.id.desc())
                    .first()
                )
                if entry:
                    entry.saved = True
                    session.commit()
            finally:
                session.close()
        except Exception as e:
            log.warning(f"Could not mark log entry saved: {e}")

    def _write_title_subject_exif(self, filepath, title, subject):
        import subprocess
        from memoria.exif_writer import _exiftool_path
        tool = _exiftool_path()
        if not tool:
            return
        args = [tool, "-overwrite_original", "-charset", "UTF8",
                f"-IPTC:ObjectName={title or ''}",
                f"-XMP-dc:Title={title or ''}",
                f"-IPTC:Caption-Abstract={subject or ''}",
                f"-XMP-dc:Description={subject or ''}",
                filepath]
        try:
            subprocess.run(args, capture_output=True, timeout=15)
        except Exception as e:
            log.warning(f"exiftool title/subject write failed: {e}")

    def _write_tags_exif(self, file_id: int, filepath: str):
        """Read current tags from DB and write them to the file's EXIF."""
        try:
            from memoria.database.models import FileTag, Tag
            from memoria.exif_writer import write_tags_to_file
            rows = (
                self._session.query(Tag.label)
                .join(FileTag, FileTag.tag_id == Tag.id)
                .filter(FileTag.file_id == file_id)
                .order_by(Tag.label)
                .all()
            )
            write_tags_to_file(filepath, [r.label for r in rows])
        except Exception as e:
            log.warning(f"Could not write tags to EXIF for file {file_id}: {e}")

    def _on_not_duplicate_requested(self, record: dict):
        file_id = record["id"]
        try:
            updated = (
                self._session.query(Duplicate)
                .filter(
                    Duplicate.reviewed == False,
                    (Duplicate.file_id_a == file_id) | (Duplicate.file_id_b == file_id),
                ).all()
            )
            if not updated:
                return
            for dup in updated:
                dup.reviewed = True
            self._session.commit()
            self._refresh_duplicate_ids()
            n = len(updated)
            self._status_label.setText(
                f"Marked {n} duplicate pair{'s' if n != 1 else ''} as reviewed"
            )
            QTimer.singleShot(3000, lambda: self._status_label.setText(
                f"{len(self._all_records):,} items"
            ))
        except Exception as e:
            self._session.rollback()
            log.error(f"Could not mark not-duplicate: {e}")

    # ── Dialog openers ────────────────────────────────────────────────────

    def _open_folder(self):
        from PyQt6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "Open Folder")
        if folder:
            # Stage 7: open a folder without adding to watch list.
            # For now inform the user and offer to add it via Options > Library.
            from PyQt6.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                self, "Open Folder",
                f"Add \"{folder}\" to the watch list and re-index?\n\n"
                "You can also manage watched folders in Options → Library.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Yes:
                from memoria.database.models import WatchedFolder
                try:
                    existing = self._session.query(WatchedFolder).filter_by(path=folder).first()
                    if existing is None:
                        self._session.add(WatchedFolder(path=folder))
                        self._session.commit()
                    self._run_index()
                except Exception as e:
                    self._session.rollback()
                    log.error(f"Could not add folder: {e}")

    def _open_about(self):
        """About dialog — app version, DB stats, module versions."""
        import os
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
        from PyQt6.QtCore import PYQT_VERSION_STR

        from memoria.config import DB_PATH
        from memoria.faces.encoding import MODEL_NAME, DETECTOR_BACKEND

        # DB size
        try:
            db_bytes = os.path.getsize(DB_PATH)
            if db_bytes >= 1024 * 1024:
                db_size = f"{db_bytes / (1024 * 1024):.1f} MB"
            else:
                db_size = f"{db_bytes / 1024:.0f} KB"
        except Exception:
            db_size = "unknown"

        # File count
        try:
            s = get_session()
            file_count = s.query(File).count()
            s.close()
            db_info = f"{file_count:,} files · {db_size}"
        except Exception:
            db_info = db_size

        # DeepFace version
        try:
            import deepface
            df_ver = deepface.__version__
        except Exception:
            df_ver = "not installed"

        dlg = QDialog(self)
        dlg.setWindowTitle("About Memoria")
        dlg.setFixedSize(420, 290)
        dlg.setStyleSheet(get_dark_style())

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(0)

        html = f"""
        <h2 style='margin:0 0 2px 0; color:#ffffff;'>Memoria</h2>
        <p style='margin:0 0 16px 0; color:#777; font-size:12px;'>
            Photo &amp; Video Manager</p>
        <table cellpadding='5' cellspacing='0' width='100%'
               style='font-size:12px; color:#d4d4d4;'>
          <tr><td style='color:#777; width:130px;'>Version</td>
              <td>1.0.0&nbsp;(Stage&nbsp;1)</td></tr>
          <tr><td style='color:#777;'>Database</td>
              <td>{db_info}</td></tr>
          <tr><td style='color:#777;'>PyQt6</td>
              <td>{PYQT_VERSION_STR}</td></tr>
          <tr><td style='color:#777;'>AI Engine</td>
              <td>DeepFace&nbsp;{df_ver}</td></tr>
          <tr><td style='color:#777;'>Face Model</td>
              <td>{MODEL_NAME}&nbsp;/&nbsp;{DETECTOR_BACKEND}</td></tr>
          <tr><td style='color:#777;'>Icons</td>
              <td>Segoe Fluent Icons (Windows 11)</td></tr>
        </table>
        """
        lbl = QLabel(html)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.setObjectName("primary")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

        dlg.exec()

    def _open_bulk_edit(self):
        from memoria.ui.bulk_edit_dialog import BulkEditDialog
        from memoria.ui.grid_view import ROLE_FILE_ID
        file_ids = {
            self._grid_model.index(r).data(ROLE_FILE_ID)
            for r in range(self._grid_model.rowCount())
        }
        records = [r for r in self._all_records if r["id"] in file_ids]
        if not records:
            return
        dlg = BulkEditDialog(self._session, records, parent=self)
        dlg.changes_applied.connect(self._load_records)
        dlg.exec()

    def _open_persons(self):
        from memoria.ui.persons_dialog import PersonsDialog
        dlg = PersonsDialog(self._session, parent=self)
        dlg.exec()
        self._load_records()

    def _open_options(self):
        from memoria.ui.options_dialog import OptionsDialog
        dlg = OptionsDialog(parent=self)
        dlg.exec()
        self.setStyleSheet(get_dark_style())
        self._set_panel_sizes()
        s = load_settings()
        if s.get("columns") != self._columns:
            self._set_columns(s["columns"])

    def _open_generate_metadata(self):
        from memoria.ui.generate_metadata_dialog import GenerateMetadataDialog
        # Use selected photos if any, otherwise current filtered view
        from memoria.ui.grid_view import ROLE_FILE_ID
        selected_ids = {
            self._grid_model.index(r).data(ROLE_FILE_ID)
            for r in range(self._grid_model.rowCount())
            if self._grid_view.selectionModel().isRowSelected(r)
        }
        # Only treat as intentional selection if >1 photo chosen;
        # a single selected item is usually just the focused/current photo.
        if len(selected_ids) > 1:
            records = [r for r in self._all_records if r["id"] in selected_ids]
        else:
            file_ids = {
                self._grid_model.index(r).data(ROLE_FILE_ID)
                for r in range(self._grid_model.rowCount())
            }
            records = [r for r in self._all_records if r["id"] in file_ids]
        if not records:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "No photos",
                                    "No photos are currently displayed to generate metadata for.")
            return
        dlg = GenerateMetadataDialog(records, self._session, parent=self)
        dlg.metadata_applied.connect(self._load_records)
        dlg.metadata_applied.connect(
            lambda: self._log_panel.refresh() if self._log_panel.isVisible() else None
        )
        dlg.exec()

    def _open_reassess(self):
        from memoria.ui.reassess_dialog import ReassessDialog
        dlg = ReassessDialog(self._session, parent=self)
        dlg.reassess_complete.connect(self._load_records)
        dlg.exec()

    def _open_duplicate_review(self):
        from memoria.ui.duplicate_review import DuplicateReviewDialog
        dlg = DuplicateReviewDialog(self)
        dlg.exec()
        self._load_records()

    def _open_face_naming(self):
        from memoria.ui.face_naming import FaceNamingDialog
        dlg = FaceNamingDialog(self)
        dlg.people_updated.connect(self._load_records)
        dlg.people_updated.connect(self.trigger_background_reassess)
        dlg.exec()

    def _run_index(self):
        from memoria.indexer.scanner import run_index
        self._status_label.setText("Indexing…")
        session = get_session()
        try:
            run_index(session)
        finally:
            session.close()
        self._load_records()

    # ── Background reassess ───────────────────────────────────────────────

    def trigger_background_reassess(self):
        try:
            running = self._bg_thread is not None and self._bg_thread.isRunning()
        except RuntimeError:
            # C++ QThread object was already deleted by deleteLater — treat as not running
            self._bg_thread = None
            running = False
        if running:
            self._bg_pending = True
            return
        self._bg_pending = False
        self._start_bg_reassess()

    def _start_bg_reassess(self):
        self._bg_stats = None
        self._bg_thread = QThread()
        self._bg_worker = _BackgroundReassessWorker()
        self._bg_worker.moveToThread(self._bg_thread)

        self._bg_worker.finished.connect(self._on_bg_worker_finished)
        self._bg_worker.finished.connect(self._bg_thread.quit)
        self._bg_thread.finished.connect(self._on_bg_thread_finished)
        self._bg_worker.finished.connect(self._bg_worker.deleteLater)
        self._bg_thread.finished.connect(self._bg_thread.deleteLater)
        self._bg_thread.started.connect(self._bg_worker.run)

        self._bg_clear_timer.stop()
        self._spinner_idx = 0
        self._bg_label.setStyleSheet(
            "color:#7c6af7; padding: 0 8px; background: transparent; font-size:12px;"
        )
        self._bg_label.setText(f"{self._spinner_frames[0]}  Re-assessing…")
        self._bg_label.show()
        self._spinner_timer.start()
        self._bg_thread.start()

    def _tick_spinner(self):
        self._spinner_idx = (self._spinner_idx + 1) % len(self._spinner_frames)
        frame = self._spinner_frames[self._spinner_idx]
        rest  = self._bg_label.text()[2:] or "  Re-assessing…"
        self._bg_label.setText(f"{frame}{rest}")

    def _on_bg_worker_finished(self, stats: dict):
        self._bg_stats = stats
        self._spinner_timer.stop()

        if "error" in stats:
            self._bg_label.setStyleSheet(
                "color:#f38ba8; padding: 0 8px; background: transparent; font-size:12px;"
            )
            self._bg_label.setText("⚠  Re-assess failed — see log")
        else:
            matched = stats.get("matched", 0)
            tags    = stats.get("tags_added", 0)
            written = stats.get("files_written", 0)
            parts   = []
            if matched: parts.append(f"{matched} face{'s' if matched != 1 else ''} matched")
            if tags:    parts.append(f"{tags} tag{'s' if tags != 1 else ''} applied")
            if written: parts.append(f"{written} file{'s' if written != 1 else ''} updated")
            summary = ", ".join(parts) if parts else "nothing new found"
            self._bg_label.setStyleSheet(
                "color:#a6e3a1; padding: 0 8px; background: transparent; font-size:12px;"
            )
            self._bg_label.setText(f"✓  Re-assess done — {summary}")
            self._load_records()

            # Log AI face assignments to the activity log
            for action in stats.get("ai_actions", []):
                self._log_edit(
                    file_id=action["file_id"],
                    filename=action["filename"],
                    filepath=action["filepath"],
                    action_type=action["action_type"],
                    old_value=action.get("old_value", ""),
                    new_value=action.get("new_value", ""),
                    source="ai",
                    saved=True,   # face assignments are immediately in the DB
                )

            if self._log_panel.isVisible():
                self._log_panel.refresh()

        self._bg_clear_timer.start()

    def _on_bg_thread_finished(self):
        # Null out the reference now, before deleteLater destroys the C++ object.
        # This prevents RuntimeError in trigger_background_reassess if it fires
        # after the thread is deleted but before Python's reference is cleared.
        self._bg_thread = None
        self._bg_worker = None
        if self._bg_pending:
            self._bg_pending = False
            self._start_bg_reassess()

    def closeEvent(self, event):
        # Check for unsaved pending edits before closing
        if self._has_pending_edits():
            from PyQt6.QtWidgets import QMessageBox
            n = self._pending_edit_count()
            reply = QMessageBox.question(
                self,
                "Unsaved changes",
                f"You have {n} pending change{'s' if n != 1 else ''} that "
                f"{'have' if n != 1 else 'has'} not been written to the files yet.\n\n"
                "These changes are saved in the Memoria database and will still be "
                "available next time you open the app — open the Activity Log to "
                "write them to the files when you're ready.\n\n"
                "Exit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        save_settings({"columns": self._columns})
        try:
            if self._bg_thread is not None and not self._bg_thread.isFinished():
                self._bg_pending = False
                self._bg_thread.quit()
                self._bg_thread.wait(5000)
        except RuntimeError:
            pass  # thread already deleted — nothing to wait for
        self._session.close()
        super().closeEvent(event)

    def _has_pending_edits(self) -> bool:
        """Return True if there are unsaved user edits in the edit_log table."""
        try:
            session = get_session()
            try:
                return session.query(EditLog).filter(
                    EditLog.saved == False,   # noqa: E712
                    EditLog.source == "user",
                ).first() is not None
            finally:
                session.close()
        except Exception:
            return False

    def _pending_edit_count(self) -> int:
        """Count of distinct files with unsaved user edits."""
        try:
            session = get_session()
            try:
                from sqlalchemy import func
                return session.query(
                    func.count(EditLog.id.distinct())
                ).filter(
                    EditLog.saved == False,   # noqa: E712
                    EditLog.source == "user",
                ).scalar() or 0
            finally:
                session.close()
        except Exception:
            return 0
