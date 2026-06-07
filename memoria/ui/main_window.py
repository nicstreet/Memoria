from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QSlider, QSplitter, QVBoxLayout, QWidget,
)

from memoria.database.db import get_session
from memoria.database.models import Duplicate, File, FilePeople, FileTag, Metadata, Person, Tag
from memoria.ui.detail_panel import DetailPanel
from memoria.ui.grid_view import PhotoGridModel, PhotoGridView
from memoria.ui.sidebar import SidebarFilters
from memoria.ui.styles import get_dark_style
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


class _BackgroundReassessWorker(QObject):
    finished = pyqtSignal(dict)   # stats

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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Memoria")
        self.resize(1400, 900)
        self.setMinimumSize(480, 360)

        self._thumbnail_cache = ThumbnailCache(self)
        self._session = get_session()
        self._all_records: list[dict] = []
        ui_settings = load_settings()
        self._columns = ui_settings.get("columns", 5)

        # Apply saved accent colour before building UI
        from memoria.ui.theme import set_accent
        set_accent(ui_settings.get("accent_colour", "#7c6af7"))
        self.setStyleSheet(get_dark_style())

        self._build_ui()
        self._build_menu()
        self._load_records()
        # Defer layout until window is fully painted
        QTimer.singleShot(200, self._on_resize_settled)

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
        self._grid_view.rotate_requested.connect(self._on_rotate_requested)
        self._grid_view.face_review_requested.connect(self._on_face_review_requested)
        self._grid_view.not_duplicate_requested.connect(self._on_not_duplicate_requested)
        self._grid_view.meta_field_changed.connect(self._on_meta_field_changed)

        # Right detail panel
        self._detail = DetailPanel(self._thumbnail_cache)
        self._detail.set_session(self._session)

        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._grid_view)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setCollapsible(0, True)    # sidebar can be hidden
        splitter.setCollapsible(2, False)
        self._splitter = splitter
        self._sidebar_visible = True

        self.setCentralWidget(splitter)

        self._status_label = QLabel("Loading…")
        self._status_label.setStyleSheet(
            "color:#9a9a9a; padding-left:4px; background: transparent;"
        )
        self.statusBar().addWidget(self._status_label)

        # Background task indicator — hidden until a task is running
        self._bg_label = QLabel()
        self._bg_label.setStyleSheet(
            "color:#7c6af7; padding: 0 8px; background: transparent; font-size:12px;"
        )
        self._bg_label.hide()
        self.statusBar().addWidget(self._bg_label)

        self._build_statusbar()

        # Background reassess state
        self._bg_thread: QThread | None = None
        self._bg_pending = False          # re-trigger queued while running
        self._spinner_frames = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
        self._spinner_idx = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(100)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        self._bg_clear_timer = QTimer(self)
        self._bg_clear_timer.setSingleShot(True)
        self._bg_clear_timer.setInterval(6000)
        self._bg_clear_timer.timeout.connect(self._bg_label.hide)

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

    def _set_panel_sizes(self):
        """Size both side panels to ~19 % of window width, centre takes the rest."""
        w = self.width()
        if w < 200:
            return
        panel = max(160, int(w * 0.19))
        if self._sidebar_visible:
            self._splitter.setSizes([panel, w - panel * 2, panel])
        else:
            self._splitter.setSizes([0, w - panel, panel])

    def _toggle_sidebar(self):
        self._sidebar_visible = not self._sidebar_visible
        self._set_panel_sizes()
        # Icon stays the same — tooltip explains state
        self._sidebar_toggle_btn.setToolTip(
            "Show filter sidebar" if not self._sidebar_visible
            else "Hide filter sidebar"
        )

    def _build_menu(self):
        menu_bar = self.menuBar()

        # Sidebar toggle button — sits to the left of the Library menu
        from memoria.ui.fluent_icons import fi, FONT_NAME
        # Wrap the toggle button in a small container with right padding
        # so the "Library" menu text doesn't overlap it
        toggle_container = QWidget()
        toggle_container.setStyleSheet("background: transparent;")
        tc_layout = QHBoxLayout(toggle_container)
        tc_layout.setContentsMargins(4, 0, 8, 0)
        tc_layout.setSpacing(0)

        self._sidebar_toggle_btn = QPushButton(fi.PANEL_LEFT)
        self._sidebar_toggle_btn.setFont(QFont(FONT_NAME, 13))
        self._sidebar_toggle_btn.setFixedSize(28, 22)
        self._sidebar_toggle_btn.setToolTip("Hide filter sidebar")
        self._sidebar_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sidebar_toggle_btn.setStyleSheet("""
            QPushButton {
                background: transparent; border: none; color: #aaa; padding: 0;
            }
            QPushButton:hover { color: #fff; background: #3a3a3a; border-radius: 3px; }
        """)
        self._sidebar_toggle_btn.clicked.connect(self._toggle_sidebar)
        tc_layout.addWidget(self._sidebar_toggle_btn)
        menu_bar.setCornerWidget(toggle_container, Qt.Corner.TopLeftCorner)

        from memoria.ui.fluent_icons import fi, make_icon

        lib_menu = menu_bar.addMenu("Library")

        index_action = QAction(make_icon(fi.REFRESH),  "Re-index folders", self)
        index_action.setShortcut("Ctrl+R")
        index_action.triggered.connect(self._run_index)
        lib_menu.addAction(index_action)

        face_action = QAction(make_icon(fi.FACE),   "Name faces…", self)
        face_action.setShortcut("Ctrl+F")
        face_action.triggered.connect(self._open_face_naming)
        lib_menu.addAction(face_action)

        persons_action = QAction(make_icon(fi.PERSON), "People…", self)
        persons_action.setShortcut("Ctrl+P")
        persons_action.triggered.connect(self._open_persons)
        lib_menu.addAction(persons_action)

        bulk_action = QAction(make_icon(fi.MULTI_SELECT), "Bulk Edit displayed photos…", self)
        bulk_action.setShortcut("Ctrl+B")
        bulk_action.triggered.connect(self._open_bulk_edit)
        lib_menu.addAction(bulk_action)

        lib_menu.addSeparator()

        reassess_action = QAction(make_icon(fi.SCAN), "Re-assess photos for faces && names…", self)
        reassess_action.setShortcut("Ctrl+Shift+R")
        reassess_action.triggered.connect(self._open_reassess)
        lib_menu.addAction(reassess_action)

        dupes_action = QAction(make_icon(fi.COPY_X), "Review duplicates…", self)
        dupes_action.setShortcut("Ctrl+D")
        dupes_action.triggered.connect(self._open_duplicate_review)
        lib_menu.addAction(dupes_action)

        lib_menu.addSeparator()

        options_action = QAction(make_icon(fi.SETTINGS), "Options…", self)
        options_action.setShortcut("Ctrl+,")
        options_action.triggered.connect(self._open_options)
        lib_menu.addAction(options_action)

        lib_menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(QApplication.quit)
        lib_menu.addAction(quit_action)

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
        self._refresh_duplicate_ids()

    def _refresh_duplicate_ids(self):
        """Push the set of file IDs with unreviewed duplicates into the grid delegate."""
        try:
            session = get_session()
            pairs = session.query(Duplicate.file_id_a, Duplicate.file_id_b)\
                           .filter(Duplicate.reviewed == False).all()
            session.close()
            dup_ids = set()
            for a, b in pairs:
                dup_ids.add(a)
                dup_ids.add(b)
            self._grid_view.set_duplicate_ids(dup_ids)
        except Exception as e:
            log.warning(f"Could not load duplicate IDs: {e}")

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

        # Build set of file IDs that have at least one unidentified face
        unidentified_ids: set[int] | None = None
        if filters.get("unidentified_faces"):
            session = get_session()
            try:
                from memoria.database.models import FaceDetection
                rows = (
                    session.query(FaceDetection.file_id)
                    .filter(FaceDetection.person_id.is_(None),
                            FaceDetection.file_id.isnot(None))
                    .distinct()
                    .all()
                )
                unidentified_ids = {r.file_id for r in rows}
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

            # Unidentified faces
            if unidentified_ids is not None and r["id"] not in unidentified_ids:
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
        """Rotate the image 90° clockwise, update DB, refresh thumbnail."""
        from PIL import Image
        from datetime import datetime

        filepath = record["filepath"]
        file_id  = record["id"]
        try:
            with Image.open(filepath) as img:
                # Rotate 90° clockwise = transpose ROTATE_270 (lossless-friendly)
                rotated = img.transpose(Image.Transpose.ROTATE_270)
                # Preserve format; strip EXIF orientation so it doesn't fight us
                fmt = img.format or "JPEG"
                save_kwargs = {"quality": 95} if fmt.upper() in ("JPEG", "JPG") else {}
                rotated.save(filepath, format=fmt, **save_kwargs)

            # Update mtime + dimensions in DB; clear face scan (bboxes are now wrong)
            from memoria.database.models import File, Metadata, FaceDetection
            file_row = self._session.query(File).get(file_id)
            if file_row:
                file_row.file_modified_at = datetime.utcnow()
                file_row.face_scanned_at  = None   # force re-scan

            meta_row = self._session.query(Metadata).filter_by(file_id=file_id).first()
            if meta_row and meta_row.width and meta_row.height:
                meta_row.width, meta_row.height = meta_row.height, meta_row.width

            # Clear face detections since bboxes are stale
            self._session.query(FaceDetection).filter_by(file_id=file_id).delete()
            self._session.commit()

            # Refresh thumbnail and detail panel
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
        """Save title or subject from the grid context menu and sync EXIF."""
        from memoria.database.models import Metadata, File
        from memoria.exif_writer import write_tags_to_file
        from memoria.database.models import FileTag, Tag
        try:
            meta = self._session.query(Metadata).filter_by(file_id=file_id).first()
            if meta is None:
                meta = Metadata(file_id=file_id)
                self._session.add(meta)
            setattr(meta, field, value or None)
            self._session.commit()

            # Write updated title/subject to EXIF
            file_row = self._session.query(File).get(file_id)
            if file_row and file_row.file_type == "photo":
                # Write EXIF title/subject via exiftool
                self._write_title_subject_exif(file_row.filepath,
                                               meta.title, meta.subject)

            # Refresh detail panel if this photo is selected
            if (self._detail._current_record or {}).get("id") == file_id:
                if field == "title":
                    self._detail._title_input.setText(value)
                else:
                    self._detail._subject_input.setText(value)
                if self._detail._current_meta is not None:
                    self._detail._current_meta[field] = value or None
                self._detail._refresh_status()

        except Exception as e:
            self._session.rollback()
            log.error(f"Could not save {field}: {e}")

    def _write_title_subject_exif(self, filepath: str,
                                   title: str | None, subject: str | None):
        """Write Title and Subject fields to file EXIF using exiftool."""
        import subprocess
        from memoria.exif_writer import _exiftool_path
        tool = _exiftool_path()
        if not tool:
            return
        args = [tool, "-overwrite_original", "-charset", "UTF8"]
        args += [f"-IPTC:ObjectName={title or ''}",
                 f"-XMP-dc:Title={title or ''}",
                 f"-IPTC:Caption-Abstract={subject or ''}",
                 f"-XMP-dc:Description={subject or ''}"]
        args.append(filepath)
        try:
            subprocess.run(args, capture_output=True, timeout=15)
        except Exception as e:
            log.warning(f"exiftool title/subject write failed: {e}")

    def _on_not_duplicate_requested(self, record: dict):
        """Mark all unreviewed duplicate pairs involving this photo as reviewed."""
        file_id = record["id"]
        try:
            updated = (
                self._session.query(Duplicate)
                .filter(
                    Duplicate.reviewed == False,
                    (Duplicate.file_id_a == file_id) | (Duplicate.file_id_b == file_id)
                )
                .all()
            )
            if not updated:
                return
            for dup in updated:
                dup.reviewed = True
            self._session.commit()

            # Remove this file from the duplicate IDs set and refresh the grid
            self._refresh_duplicate_ids()
            # Update status bar briefly
            n = len(updated)
            self._status_label.setText(
                f"Marked {n} duplicate pair{'s' if n != 1 else ''} as reviewed"
            )
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(3000, lambda: self._status_label.setText(
                f"{len(self._all_records):,} items"
            ))
        except Exception as e:
            self._session.rollback()
            log.error(f"Could not mark not-duplicate: {e}")

    def _open_persons(self):
        from memoria.ui.persons_dialog import PersonsDialog
        dlg = PersonsDialog(self._session, parent=self)
        dlg.exec()
        self._load_records()   # refresh grid/sidebar in case names or tags changed

    def _open_options(self):
        from memoria.ui.options_dialog import OptionsDialog
        dlg = OptionsDialog(parent=self)
        dlg.exec()
        from memoria.ui.styles import get_dark_style
        from memoria.ui.settings_store import load
        self.setStyleSheet(get_dark_style())
        self._set_panel_sizes()
        s = load()
        if s.get("columns") != self._columns:
            self._set_columns(s["columns"])

    def _open_reassess(self):
        from memoria.ui.reassess_dialog import ReassessDialog
        dlg = ReassessDialog(self._session, parent=self)
        dlg.reassess_complete.connect(self._load_records)
        dlg.exec()

    def _open_duplicate_review(self):
        from memoria.ui.duplicate_review import DuplicateReviewDialog
        dlg = DuplicateReviewDialog(self)
        dlg.exec()
        self._load_records()  # refresh grid in case files were trashed

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

    # ── Background reassess ───────────────────────────────────────────────────

    def trigger_background_reassess(self):
        """Start a background re-assess, or queue one if already running."""
        if self._bg_thread and self._bg_thread.isRunning():
            self._bg_pending = True
            log.debug("Background reassess already running — queued another pass")
            return
        self._bg_pending = False
        self._start_bg_reassess()

    def _start_bg_reassess(self):
        self._bg_stats = None                        # cleared each run
        self._bg_thread = QThread()
        self._bg_worker = _BackgroundReassessWorker()
        self._bg_worker.moveToThread(self._bg_thread)

        # worker.finished  → capture stats + stop spinner + ask thread to stop
        self._bg_worker.finished.connect(self._on_bg_worker_finished)
        self._bg_worker.finished.connect(self._bg_thread.quit)

        # thread.finished  → thread OS resources gone; now safe to start next run
        self._bg_thread.finished.connect(self._on_bg_thread_finished)

        # Clean up Qt objects once the thread has stopped
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
        current = self._bg_label.text()
        rest    = current[2:] if len(current) > 2 else "  Re-assessing…"
        self._bg_label.setText(f"{frame}{rest}")

    def _on_bg_worker_finished(self, stats: dict):
        """Worker has finished — update the UI. Thread is still shutting down."""
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
            if matched:  parts.append(f"{matched} face{'s' if matched != 1 else ''} matched")
            if tags:     parts.append(f"{tags} tag{'s' if tags != 1 else ''} applied")
            if written:  parts.append(f"{written} file{'s' if written != 1 else ''} updated")
            summary = ", ".join(parts) if parts else "nothing new found"
            self._bg_label.setStyleSheet(
                "color:#a6e3a1; padding: 0 8px; background: transparent; font-size:12px;"
            )
            self._bg_label.setText(f"✓  Re-assess done — {summary}")
            self._load_records()

        self._bg_clear_timer.start()

    def _on_bg_thread_finished(self):
        """Thread OS resources are fully released — safe to start another run."""
        if self._bg_pending:
            self._bg_pending = False
            self._start_bg_reassess()

    def closeEvent(self, event):
        save_settings({"columns": self._columns})
        # Stop any running background reassess cleanly before exit
        if self._bg_thread and not self._bg_thread.isFinished():
            self._bg_pending = False          # don't re-trigger after quit
            self._bg_thread.quit()
            self._bg_thread.wait(5000)        # wait up to 5 s for clean exit
        self._session.close()
        super().closeEvent(event)
