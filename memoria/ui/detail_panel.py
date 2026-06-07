from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap, QImageReader
from PyQt6.QtWidgets import (
    QCompleter, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from memoria.ui.thumbnail_cache import ThumbnailCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_size(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


_ORIENTATION_LABELS = {
    1: "Normal",
    2: "Mirrored horizontal",
    3: "Rotated 180°",
    4: "Mirrored vertical",
    5: "Mirrored horizontal, rotated 90° CCW",
    6: "Rotated 90° CW",
    7: "Mirrored horizontal, rotated 90° CW",
    8: "Rotated 90° CCW",
}

def _get_orientation_label(filepath: str) -> str | None:
    try:
        import exifread
        with open(filepath, "rb") as f:
            tags = exifread.process_file(f, stop_tag="Image Orientation", details=False)
        tag = tags.get("Image Orientation")
        if tag and tag.values:
            val = tag.values[0]
            return _ORIENTATION_LABELS.get(int(str(val)), None)
    except Exception:
        pass
    return None

def _exif_orientation(filepath: str) -> int:
    """Return EXIF orientation tag value (1-8), or 1 if absent/unreadable."""
    try:
        reader = QImageReader(filepath)
        return reader.transformation()
    except Exception:
        return 0


def _apply_orientation(px: QPixmap, filepath: str) -> QPixmap:
    """Rotate/flip pixmap to match EXIF orientation."""
    try:
        import exifread
        with open(filepath, "rb") as f:
            tags = exifread.process_file(f, stop_tag="Image Orientation", details=False)
        tag = tags.get("Image Orientation")
        if tag is None:
            return px
        val = tag.values[0] if tag.values else 1
        from PyQt6.QtGui import QTransform
        t = QTransform()
        if val == 3:   t.rotate(180)
        elif val == 6: t.rotate(90)
        elif val == 8: t.rotate(-90)
        elif val == 2: t.scale(-1, 1)
        elif val == 4: t.rotate(180); t.scale(-1, 1)
        elif val == 5: t.rotate(90);  t.scale(-1, 1)
        elif val == 7: t.rotate(-90); t.scale(-1, 1)
        if val != 1:
            return px.transformed(t, Qt.TransformationMode.SmoothTransformation)
    except Exception:
        pass
    return px


# ---------------------------------------------------------------------------
# Tag chip widget
# ---------------------------------------------------------------------------

class _TagChip(QWidget):
    removed = pyqtSignal(int)   # tag_id

    def __init__(self, tag_id: int, label: str, parent=None):
        super().__init__(parent)
        self.tag_id = tag_id
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 1, 4, 1)
        layout.setSpacing(3)

        lbl = QLabel(label)
        lbl.setStyleSheet("color:#d4d4d4; font-size:11px;")
        layout.addWidget(lbl)

        btn = QPushButton("×")
        btn.setFixedSize(14, 14)
        btn.setFlat(True)
        btn.setStyleSheet("color:#888; font-size:12px; border:none; padding:0;")
        btn.clicked.connect(lambda: self.removed.emit(self.tag_id))
        layout.addWidget(btn)

        self.setStyleSheet("""
            QWidget {
                background: #3a3a5a;
                border-radius: 10px;
            }
        """)


# ---------------------------------------------------------------------------
# Detail Panel
# ---------------------------------------------------------------------------

class DetailPanel(QWidget):
    tag_added = pyqtSignal(int, str)    # file_id, tag_label
    tag_removed = pyqtSignal(int, int)  # file_id, tag_id

    def __init__(self, thumbnail_cache: ThumbnailCache, parent=None):
        super().__init__(parent)
        self.setObjectName("detailPanel")
        self.setMinimumWidth(160)
        self._cache = thumbnail_cache
        self._current_record: dict | None = None
        self._current_meta: dict | None = None
        self._session = None
        self._build_ui()

    def set_session(self, session):
        """Inject DB session for tag operations."""
        self._session = session

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Thumbnail
        self._thumb_label = QLabel()
        self._thumb_label.setMinimumSize(160, 160)
        self._thumb_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setStyleSheet("background:#1a1a1a; border-radius:4px;")
        layout.addWidget(self._thumb_label)

        # Filename — same font/size as metadata values
        self._title = QLabel("Select a photo")
        self._title.setWordWrap(True)
        self._title.setStyleSheet("color:#d4d4d4; font-size:12px;")
        layout.addWidget(self._title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #444;")
        layout.addWidget(sep)

        # ── Status bar ────────────────────────────────────────────────────────
        self._status_widget = QWidget()
        self._status_widget.setStyleSheet("background: transparent;")
        status_row = QHBoxLayout(self._status_widget)
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(6)

        self._dot_title   = QLabel()
        self._dot_subject = QLabel()
        self._dot_face    = QLabel()
        self._dot_renamed = QLabel()
        self._status_score_lbl = QLabel()
        self._status_score_lbl.setStyleSheet("color:#777; font-size:10px;")

        for dot in (self._dot_title, self._dot_subject,
                    self._dot_face, self._dot_renamed):
            dot.setFixedSize(14, 14)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setStyleSheet("font-size:11px;")
            status_row.addWidget(dot)

        status_row.addWidget(self._status_score_lbl)
        status_row.addStretch()
        layout.addWidget(self._status_widget)
        self._status_widget.hide()

        # ── Title input ───────────────────────────────────────────────────────
        self._title_input = QLineEdit()
        self._title_input.setPlaceholderText("Title…")
        self._title_input.setStyleSheet("""
            QLineEdit {
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; color: #d4d4d4; padding: 3px 6px; font-size:11px;
            }
            QLineEdit:focus { border-color: #7c6af7; }
        """)
        self._title_input.editingFinished.connect(self._on_title_changed)
        layout.addWidget(self._title_input)

        # ── Subject input + dropdown ──────────────────────────────────────────
        subject_row = QHBoxLayout()
        subject_row.setSpacing(4)
        subject_row.setContentsMargins(0, 0, 0, 0)

        self._subject_input = QLineEdit()
        self._subject_input.setPlaceholderText("Subject…")
        self._subject_input.setStyleSheet("""
            QLineEdit {
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; color: #d4d4d4; padding: 3px 6px; font-size:11px;
            }
            QLineEdit:focus { border-color: #7c6af7; }
        """)
        self._subject_input.editingFinished.connect(self._on_subject_changed)

        # QCompleter for type-ahead
        from memoria.ui.default_subjects import ALL_SUBJECTS
        _completer = QCompleter(ALL_SUBJECTS, self._subject_input)
        _completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        _completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._subject_input.setCompleter(_completer)

        subject_row.addWidget(self._subject_input)

        # Dropdown ▾ — hierarchical subject menu
        self._subj_drop_btn = QPushButton("▾")
        self._subj_drop_btn.setFixedSize(24, 24)
        self._subj_drop_btn.setToolTip("Choose from default subjects")
        self._subj_drop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._subj_drop_btn.setStyleSheet(
            "QPushButton { background:#3a3a3a; border:1px solid #555;"
            "  border-radius:4px; color:#aaa; font-size:11px; padding:0; }"
            "QPushButton:hover { background:#4a4a4a; color:#fff; }"
        )
        self._subj_drop_btn.clicked.connect(self._show_subject_menu)
        subject_row.addWidget(self._subj_drop_btn)

        layout.addLayout(subject_row)

        sep1b = QFrame()
        sep1b.setFrameShape(QFrame.Shape.HLine)
        sep1b.setStyleSheet("color: #444;")
        layout.addWidget(sep1b)

        # Add tag input — above metadata so personalisation is first action
        tag_row = QHBoxLayout()
        tag_row.setSpacing(4)
        self._tag_input = QLineEdit()
        self._tag_input.setPlaceholderText("Add tag…")
        self._tag_input.setStyleSheet("""
            QLineEdit {
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; color: #d4d4d4; padding: 3px 6px; font-size:11px;
            }
            QLineEdit:focus { border-color: #7c6af7; }
        """)
        self._tag_input.returnPressed.connect(self._on_add_tag)
        tag_row.addWidget(self._tag_input)

        add_btn = QPushButton("+")
        add_btn.setFixedWidth(28)
        add_btn.setFlat(True)
        add_btn.setStyleSheet(
            "color:#aaa; font-size:18px; font-weight:bold; border:none; background:transparent; padding:0;"
        )
        add_btn.clicked.connect(self._on_add_tag)
        tag_row.addWidget(add_btn)
        layout.addLayout(tag_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #444;")
        layout.addWidget(sep2)

        # Scrollable metadata (includes tags chips)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        meta_widget = QWidget()
        meta_widget.setStyleSheet("background: transparent;")
        self._meta_layout = QVBoxLayout(meta_widget)
        self._meta_layout.setContentsMargins(0, 0, 0, 0)
        self._meta_layout.setSpacing(6)
        self._meta_layout.addStretch()
        scroll.setWidget(meta_widget)
        layout.addWidget(scroll, stretch=1)

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet("color: #444;")
        layout.addWidget(sep3)

        # Open file button
        self._open_btn = QPushButton("Open in default app")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_file)
        layout.addWidget(self._open_btn)

    # ── Public API ───────────────────────────────────────────────────────────

    def show_file(self, record: dict, meta: dict | None = None):
        self._current_record = record
        self._current_meta = meta

        # Thumbnail with EXIF orientation correction
        px = self._cache.get(record["id"], record["filepath"], record["file_type"])
        if record["file_type"] == "photo":
            px = _apply_orientation(px, record["filepath"])
        size = self._thumb_label.width() or 200
        self._thumb_label.setPixmap(
            px.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)
        )

        self._title.setText(record.get("filename", ""))

        # Title / subject / status
        self._title_input.blockSignals(True)
        self._subject_input.blockSignals(True)
        self._title_input.setText(meta.get("title") or "" if meta else "")
        self._subject_input.setText(meta.get("subject") or "" if meta else "")
        self._title_input.blockSignals(False)
        self._subject_input.blockSignals(False)
        if record.get("file_type") == "photo":
            self._title_input.show()
            self._subject_input.show()
            self._subj_drop_btn.show()
            self._status_widget.show()
            self._refresh_status()
        else:
            self._title_input.hide()
            self._subject_input.hide()
            self._subj_drop_btn.hide()
            self._status_widget.hide()

        self._clear_meta()

        # Metadata rows
        # Type + dimensions on one line
        file_type = record.get("file_type", "").capitalize()
        if meta and meta.get("width") and meta.get("height"):
            self._add_meta("Type", f"{file_type}  ({meta['width']} × {meta['height']})")
        else:
            self._add_meta("Type", file_type)

        date = meta.get("date_taken") if meta else record.get("date_taken")
        if date:
            self._add_meta("Date taken", date.strftime("%d/%m/%Y - %H:%M"))

        if meta:
            if meta.get("camera_make") or meta.get("camera_model"):
                camera = " ".join(filter(None, [meta.get("camera_make"), meta.get("camera_model")]))
                self._add_meta("Camera", camera)
            if record.get("file_type") == "photo":
                orientation = _get_orientation_label(record["filepath"])
                if orientation:
                    self._add_meta("Orientation", orientation)
            if meta.get("duration_seconds"):
                secs = int(meta["duration_seconds"])
                self._add_meta("Duration", f"{secs // 60}m {secs % 60}s")
            if meta.get("location_label"):
                self._add_location(meta["location_label"], meta.get("gps_lat"), meta.get("gps_lon"))
            elif meta.get("gps_lat"):
                self._add_location(None, meta["gps_lat"], meta["gps_lon"])

        # People
        if self._session:
            self._add_people(record["id"])

        try:
            size = Path(record["filepath"]).stat().st_size
            self._add_meta("File size", _fmt_size(size))
        except OSError:
            pass

        self._add_meta("Path", record.get("filepath", ""), small=True)

        # Tags — shown both as inline text in metadata and as removable chips below
        if self._session:
            self._add_tags_meta(record["id"])

        self._refresh_tags(record["id"])

        self._open_btn.setEnabled(True)
        # Only show face review for photos that have been face-scanned
        is_photo = record.get("file_type") == "photo"

    def clear(self):
        self._current_record = None
        self._thumb_label.clear()
        self._thumb_label.setStyleSheet("background:#1a1a1a; border-radius:4px;")
        self._title.setText("Select a photo")
        self._title_input.clear()
        self._subject_input.clear()
        self._title_input.hide()
        self._subject_input.hide()
        self._subj_drop_btn.hide()
        self._status_widget.hide()
        self._clear_meta()
        self._clear_tags()
        self._open_btn.setEnabled(False)

    # ── Metadata helpers ─────────────────────────────────────────────────────

    def _clear_meta(self):
        while self._meta_layout.count() > 1:
            item = self._meta_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_meta(self, label: str, value: str, small: bool = False,
                  prop: tuple | None = None):
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        if prop:
            row.setProperty(prop[0], prop[1])
        v = QVBoxLayout(row)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)

        lbl = QLabel(label)
        lbl.setStyleSheet("color:#555; font-size:10px; font-weight:bold;")
        v.addWidget(lbl)

        val = QLabel(value)
        val.setWordWrap(True)
        val.setStyleSheet(f"color:#d4d4d4; font-size:{'11' if small else '12'}px;")
        v.addWidget(val)

        self._meta_layout.insertWidget(self._meta_layout.count() - 1, row)

    def _add_location(self, label: str | None, lat: float | None, lon: float | None):
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        v = QVBoxLayout(row)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        hdr = QLabel("Location")
        hdr.setStyleSheet("color:#555; font-size:10px; font-weight:bold;")
        v.addWidget(hdr)

        # Location text + optional map icon on the same row
        display = label or (f"{lat:.4f}, {lon:.4f}" if lat is not None else "Unknown")
        loc_lbl = QLabel(display)
        loc_lbl.setWordWrap(True)
        loc_lbl.setStyleSheet("color:#d4d4d4; font-size:12px;")

        if lat is not None and lon is not None:
            from memoria.ui.fluent_icons import fi, FONT_NAME
            map_btn = QPushButton(fi.MAP_PIN)
            map_btn.setFont(QFont(FONT_NAME, 13))
            map_btn.setFixedSize(26, 26)
            map_btn.setToolTip(f"Open in Maps ({lat:.4f}, {lon:.4f})")
            map_btn.setStyleSheet(
                "QPushButton { background:#3a3a3a; color:#d4d4d4; border:1px solid #555;"
                "              border-radius:4px; padding:0; }"
                "QPushButton:hover { background:#4a4a4a; }"
            )
            map_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            map_btn.clicked.connect(
                lambda checked=False, la=lat, lo=lon:
                    os.startfile(f"https://maps.google.com/?q={la},{lo}")
            )
            loc_row = QHBoxLayout()
            loc_row.setContentsMargins(0, 0, 0, 0)
            loc_row.setSpacing(4)
            loc_row.addWidget(loc_lbl, stretch=1)
            loc_row.addWidget(map_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
            v.addLayout(loc_row)
        else:
            v.addWidget(loc_lbl)

        self._meta_layout.insertWidget(self._meta_layout.count() - 1, row)

    def _refresh_tags_meta(self):
        """Refresh both the inline tags metadata row and the chip row."""
        if self._current_record:
            self._remove_tags_meta_widget()
            self._add_tags_meta(self._current_record["id"])
            self._refresh_tags(self._current_record["id"])

    def _remove_tags_meta_widget(self):
        """Remove the plain-text Tags metadata row if present."""
        for i in range(self._meta_layout.count()):
            item = self._meta_layout.itemAt(i)
            if item and item.widget() and item.widget().property("is_tags_meta"):
                w = self._meta_layout.takeAt(i).widget()
                w.deleteLater()
                return

    def _add_tags_meta(self, file_id: int):
        """Show current tags as a comma-separated line in the metadata section."""
        try:
            from memoria.database.models import FileTag, Tag
            rows = (
                self._session.query(Tag.label)
                .join(FileTag, FileTag.tag_id == Tag.id)
                .filter(FileTag.file_id == file_id)
                .order_by(Tag.label)
                .all()
            )
            if rows:
                self._add_meta("Tags", ", ".join(r.label for r in rows),
                               prop=("is_tags_meta", True))
        except Exception:
            pass

    def _add_people(self, file_id: int):
        try:
            from memoria.database.models import FilePeople, Person
            rows = (
                self._session.query(Person.name)
                .join(FilePeople, FilePeople.person_id == Person.id)
                .filter(FilePeople.file_id == file_id)
                .all()
            )
            if rows:
                names = ", ".join(r.name for r in rows)
                self._add_meta("People", names)
        except Exception:
            pass

    # ── Tag helpers ───────────────────────────────────────────────────────────

    def _remove_tags_widget(self):
        """Remove the tags widget from the metadata layout if present."""
        for i in range(self._meta_layout.count()):
            item = self._meta_layout.itemAt(i)
            if item and item.widget() and item.widget().property("is_tags_widget"):
                w = self._meta_layout.takeAt(i).widget()
                w.deleteLater()
                return

    def _refresh_tags(self, file_id: int):
        """Rebuild tags chips inside the metadata layout."""
        self._remove_tags_widget()
        if not self._session:
            return
        try:
            from memoria.database.models import FileTag, Tag
            rows = (
                self._session.query(Tag.id, Tag.label)
                .join(FileTag, FileTag.tag_id == Tag.id)
                .filter(FileTag.file_id == file_id)
                .all()
            )

            container = QWidget()
            container.setProperty("is_tags_widget", True)
            container.setStyleSheet("background: transparent;")
            v = QVBoxLayout(container)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)

            if rows:
                row_widget = None
                row_layout = None
                for count, (tag_id, label) in enumerate(rows):
                    if count % 2 == 0:
                        row_widget = QWidget()
                        row_widget.setStyleSheet("background:transparent;")
                        row_layout = QHBoxLayout(row_widget)
                        row_layout.setContentsMargins(0, 0, 0, 0)
                        row_layout.setSpacing(4)
                        v.addWidget(row_widget)
                    chip = _TagChip(tag_id, label)
                    chip.removed.connect(self._on_remove_tag)
                    row_layout.addWidget(chip)
                if len(rows) % 2 == 1:
                    row_layout.addStretch()
            else:
                none_lbl = QLabel("No tags")
                none_lbl.setStyleSheet("color:#555; font-size:11px;")
                v.addWidget(none_lbl)

            # Insert before the stretch at the end
            self._meta_layout.insertWidget(self._meta_layout.count() - 1, container)
        except Exception:
            pass

    def _on_add_tag(self):
        if not self._current_record or not self._session:
            return
        label = self._tag_input.text().strip()
        if not label:
            return
        try:
            from memoria.database.models import FileTag, Tag
            tag = self._session.query(Tag).filter_by(label=label).first()
            if tag is None:
                tag = Tag(label=label)
                self._session.add(tag)
                self._session.flush()
            existing = (
                self._session.query(FileTag)
                .filter_by(file_id=self._current_record["id"], tag_id=tag.id)
                .first()
            )
            if not existing:
                self._session.add(FileTag(
                    file_id=self._current_record["id"], tag_id=tag.id
                ))
                self._session.commit()
            self._tag_input.clear()
            self._refresh_tags(self._current_record["id"])
            self._refresh_tags_meta()
            self.tag_added.emit(self._current_record["id"], label)
            self._sync_tags_to_file()
            self._refresh_status()
        except Exception as e:
            self._session.rollback()

    def _on_remove_tag(self, tag_id: int):
        if not self._current_record or not self._session:
            return
        try:
            from memoria.database.models import FileTag
            self._session.query(FileTag).filter_by(
                file_id=self._current_record["id"], tag_id=tag_id
            ).delete()
            self._session.commit()
            self._refresh_tags(self._current_record["id"])
            self._refresh_tags_meta()
            self.tag_removed.emit(self._current_record["id"], tag_id)
            self._sync_tags_to_file()
        except Exception:
            self._session.rollback()

    def _sync_tags_to_file(self):
        """Write the current tag set for the displayed photo to its EXIF/IPTC metadata."""
        if not self._current_record or not self._session:
            return
        if self._current_record.get("file_type") != "photo":
            return
        try:
            from memoria.database.models import FileTag, Tag
            from memoria.exif_writer import write_tags_to_file
            rows = (
                self._session.query(Tag.label)
                .join(FileTag, FileTag.tag_id == Tag.id)
                .filter(FileTag.file_id == self._current_record["id"])
                .order_by(Tag.label)
                .all()
            )
            tags = [r.label for r in rows]
            write_tags_to_file(self._current_record["filepath"], tags)
        except Exception as e:
            log.warning(f"Could not sync tags to file: {e}")

    # ── Resize / open ─────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        available = self.width() - 24
        size = max(160, available)
        self._thumb_label.setFixedSize(size, size)
        if self._current_record:
            px = self._cache.get(
                self._current_record["id"],
                self._current_record["filepath"],
                self._current_record["file_type"],
            )
            if self._current_record["file_type"] == "photo":
                px = _apply_orientation(px, self._current_record["filepath"])
            self._thumb_label.setPixmap(
                px.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )

    # ── Title / subject / status ──────────────────────────────────────────────

    def _on_title_changed(self):
        if not self._current_record or not self._session:
            return
        self._save_meta_field("title", self._title_input.text().strip())

    def _on_subject_changed(self):
        if not self._current_record or not self._session:
            return
        self._save_meta_field("subject", self._subject_input.text().strip())

    def _save_meta_field(self, field: str, value: str):
        from memoria.database.models import Metadata
        try:
            meta = self._session.query(Metadata).filter_by(
                file_id=self._current_record["id"]
            ).first()
            if meta is None:
                meta = Metadata(file_id=self._current_record["id"])
                self._session.add(meta)
            setattr(meta, field, value or None)
            self._session.commit()
            # Keep current_meta in sync so status is correct
            if self._current_meta is not None:
                self._current_meta[field] = value or None
            # Write title/subject to EXIF
            self._sync_title_subject_exif(meta)
            self._refresh_status()
        except Exception as e:
            self._session.rollback()
            log.warning(f"Could not save {field}: {e}")

    def _sync_title_subject_exif(self, meta):
        """Write title and subject to the file's EXIF metadata via exiftool."""
        if not self._current_record:
            return
        if self._current_record.get("file_type") != "photo":
            return
        try:
            import subprocess
            from memoria.exif_writer import _exiftool_path
            tool = _exiftool_path()
            if not tool:
                return
            title   = getattr(meta, "title",   None) or ""
            subject = getattr(meta, "subject", None) or ""
            args = [
                tool, "-overwrite_original", "-charset", "UTF8",
                f"-IPTC:ObjectName={title}",
                f"-XMP-dc:Title={title}",
                f"-IPTC:Caption-Abstract={subject}",
                f"-XMP-dc:Description={subject}",
                self._current_record["filepath"],
            ]
            subprocess.run(args, capture_output=True, timeout=15)
        except Exception as e:
            log.warning(f"Could not write title/subject to EXIF: {e}")

    def _refresh_status(self):
        """Recompute the 4-dot status row and trigger auto-rename if ready."""
        if not self._current_record or not self._session:
            return
        from memoria.file_status import compute_status, maybe_auto_rename

        st = compute_status(self._current_record["id"], self._session)

        from memoria.ui.theme import accent
        a = accent()

        def _dot(ok: bool, na: bool = False) -> str:
            return "—" if na else ("●" if ok else "○")

        def _style(ok: bool, na: bool = False) -> str:
            if na:  return "color:#555; font-size:12px;"
            if ok:  return f"color:{a}; font-size:12px;"
            return          "color:#555; font-size:12px;"

        face_na = st["face_detail"] == "none"

        dots = [
            (self._dot_title,   st["has_title"],   False,   "Title"),
            (self._dot_subject, st["has_subject"],  False,   "Subject"),
            (self._dot_face,    st["face_ok"],      face_na, "Named face" if not face_na else "No faces"),
            (self._dot_renamed, st["renamed"],      False,   "Renamed"),
        ]
        for lbl, ok, na, tip in dots:
            lbl.setText(_dot(ok, na))
            lbl.setStyleSheet(_style(ok, na))
            lbl.setToolTip(tip)

        self._status_score_lbl.setText(f"{st['score']}/4")

        # Auto-rename when conditions 1–3 met and not yet renamed
        if not st["renamed"] and st["has_title"] and st["has_subject"] and st["face_ok"]:
            renamed = maybe_auto_rename(self._current_record["id"], self._session)
            if renamed:
                # Reload file record with new filename/path
                from memoria.database.models import File
                fr = self._session.query(File).get(self._current_record["id"])
                if fr:
                    self._current_record["filepath"] = fr.filepath
                    self._current_record["filename"]  = fr.filename
                    self._title.setText(fr.filename)
                self._refresh_status()

    def _show_subject_menu(self):
        """Pop up a hierarchical menu of default subjects."""
        from memoria.ui.default_subjects import SUBJECT_CATEGORIES
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background:#252526; color:#d4d4d4;
                border:1px solid #444; border-radius:4px;
            }
            QMenu::item { padding:4px 24px 4px 12px; font-size:12px; }
            QMenu::item:selected { background:#5a4fd4; color:#fff; }
            QMenu::separator { height:1px; background:#444; margin:3px 0; }
        """)
        for category, subjects in SUBJECT_CATEGORIES:
            sub = menu.addMenu(category)
            sub.setStyleSheet(menu.styleSheet())
            for subject in subjects:
                act = sub.addAction(subject)
                act.triggered.connect(
                    lambda checked=False, s=subject: self._set_subject(s)
                )
        menu.exec(self._subj_drop_btn.mapToGlobal(
            self._subj_drop_btn.rect().bottomLeft()
        ))

    def _set_subject(self, subject: str):
        """Set the subject input and immediately save."""
        self._subject_input.setText(subject)
        self._on_subject_changed()

    def _open_face_review(self):
        if not self._current_record or not self._session:
            return
        from memoria.ui.face_review import FaceReviewDialog
        dlg = FaceReviewDialog(self._session, self._current_record, parent=self)
        dlg.people_changed.connect(lambda: self._add_people(self._current_record["id"]))
        dlg.exec()
        # Refresh people and tags in case assignments changed
        self._clear_meta()
        self.show_file(self._current_record, self._current_meta)

    def _open_file(self):
        if self._current_record:
            filepath = self._current_record.get("filepath", "")
            if filepath and Path(filepath).exists():
                os.startfile(filepath)
