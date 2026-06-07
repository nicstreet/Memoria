"""
Face Review Dialog
──────────────────
Shows a photo with bounding-box overlays for every detected face.
• Click an unnamed face to assign a name.
• After naming, a tag-suggestion dialog offers tags seen on other
  photos of that same person.
• Named faces stay highlighted in green so you can see progress.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPen, QPixmap, QBrush,
    QFontMetrics,
)
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

log = logging.getLogger(__name__)

# ── Colours ──────────────────────────────────────────────────────────────────
_COL_UNNAMED  = QColor(255, 165,  50, 220)   # orange
_COL_NAMED    = QColor( 80, 200, 120, 220)   # green
_COL_HOVER    = QColor(124, 106, 247, 220)   # purple accent
_COL_LABEL_BG = QColor(  0,   0,   0, 160)


# ─────────────────────────────────────────────────────────────────────────────
# Photo widget — renders image + face boxes, handles click
# ─────────────────────────────────────────────────────────────────────────────

class _PhotoFaceView(QLabel):
    """QLabel subclass that draws face bounding boxes and emits face_clicked(det_id)."""

    face_clicked = pyqtSignal(int)   # detection id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

        self._detections: list[dict] = []   # [{id, bbox, name, person_id}]
        self._scale   = 1.0
        self._offset  = QPoint(0, 0)        # top-left of image inside label
        self._hover_id: int | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, filepath: str, detections: list[dict]):
        """Load image and detection list. detections: list of dicts with keys
        id, bbox_x, bbox_y, bbox_w, bbox_h, name (str|None)."""
        self._detections = detections
        self._hover_id   = None

        px = QPixmap(filepath)
        if px.isNull():
            self.setText("Cannot load image")
            return

        # Apply EXIF orientation
        try:
            import exifread
            with open(filepath, "rb") as f:
                tags = exifread.process_file(f, stop_tag="Image Orientation", details=False)
            tag = tags.get("Image Orientation")
            if tag and tag.values:
                from PyQt6.QtGui import QTransform
                v = tag.values[0]
                t = QTransform()
                if   v == 3: t.rotate(180)
                elif v == 6: t.rotate(90)
                elif v == 8: t.rotate(-90)
                if v != 1:
                    px = px.transformed(t, Qt.TransformationMode.SmoothTransformation)
        except Exception:
            pass

        self._orig_px = px
        self._refresh_pixmap()

    def refresh_detections(self, detections: list[dict]):
        self._detections = detections
        self._refresh_pixmap()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _refresh_pixmap(self):
        if not hasattr(self, "_orig_px"):
            return
        w = self.width()  or 600
        h = self.height() or 500
        scaled = self._orig_px.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._scale  = scaled.width() / self._orig_px.width()
        self._offset = QPoint(
            (w - scaled.width())  // 2,
            (h - scaled.height()) // 2,
        )

        # Draw boxes on a copy
        canvas = scaled.copy()
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        painter.setFont(font)
        fm = QFontMetrics(font)

        for det in self._detections:
            is_hover = det["id"] == self._hover_id
            named    = bool(det.get("name"))
            colour   = _COL_HOVER if is_hover else (_COL_NAMED if named else _COL_UNNAMED)

            sx = int(det["bbox_x"] * self._scale)
            sy = int(det["bbox_y"] * self._scale)
            sw = int(det["bbox_w"] * self._scale)
            sh = int(det["bbox_h"] * self._scale)

            pen = QPen(colour, 2 if named else 2)
            if not named:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(sx, sy, sw, sh)

            # Name label
            label_text = det["name"] if named else "?"
            text_w = fm.horizontalAdvance(label_text) + 8
            text_h = fm.height() + 4
            label_rect = QRect(sx, max(0, sy - text_h), text_w, text_h)

            painter.fillRect(label_rect, _COL_LABEL_BG)
            painter.setPen(QPen(colour))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label_text)

        painter.end()
        self.setPixmap(canvas)

    def _det_at(self, pos: QPoint) -> dict | None:
        """Return detection dict under mouse position (label coords), or None."""
        lp = pos - self._offset
        for det in self._detections:
            sx = int(det["bbox_x"] * self._scale)
            sy = int(det["bbox_y"] * self._scale)
            sw = int(det["bbox_w"] * self._scale)
            sh = int(det["bbox_h"] * self._scale)
            if QRect(sx, sy, sw, sh).contains(lp):
                return det
        return None

    # ── Events ────────────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_pixmap()

    def mouseMoveEvent(self, event):
        det = self._det_at(event.pos())
        new_id = det["id"] if det else None
        if new_id != self._hover_id:
            self._hover_id = new_id
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if det
                else Qt.CursorShape.CrossCursor
            )
            self._refresh_pixmap()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            det = self._det_at(event.pos())
            if det:
                self.face_clicked.emit(det["id"])


# ─────────────────────────────────────────────────────────────────────────────
# Name picker dialog (shown when clicking an unnamed face)
# ─────────────────────────────────────────────────────────────────────────────

class _NamePickerDialog(QDialog):
    def __init__(self, known_people: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Assign name")
        self.setMinimumWidth(280)
        self.setStyleSheet("""
            QDialog { background: #1e1e1e; color: #d4d4d4; }
            QLabel  { color: #d4d4d4; }
            QComboBox, QLineEdit {
                background: #3a3a3a; border: 1px solid #555; border-radius: 4px;
                color: #d4d4d4; padding: 4px 8px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #2d2d2d; color: #d4d4d4;
                selection-background-color: #5a4fd4; border: 1px solid #555;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(QLabel("Select an existing person or type a new name:"))

        self._combo = QComboBox()
        self._combo.addItem("— new person —", None)
        for name in sorted(known_people):
            self._combo.addItem(name, name)
        self._combo.currentIndexChanged.connect(self._on_combo)
        layout.addWidget(self._combo)

        self._new_name = QLineEdit()
        self._new_name.setPlaceholderText("New person's name…")
        layout.addWidget(self._new_name)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        btns.setStyleSheet("QPushButton { background:#3a3a3a; color:#d4d4d4; border:1px solid #555; border-radius:4px; padding:4px 12px; } QPushButton:hover{background:#4a4a4a;}")
        layout.addWidget(btns)

    def _on_combo(self):
        existing = self._combo.currentData()
        self._new_name.setEnabled(existing is None)
        if existing:
            self._new_name.clear()

    def chosen_name(self) -> str | None:
        existing = self._combo.currentData()
        if existing:
            return existing
        name = self._new_name.text().strip()
        return name if name else None


# ─────────────────────────────────────────────────────────────────────────────
# Main dialog
# ─────────────────────────────────────────────────────────────────────────────

class FaceReviewDialog(QDialog):
    """
    Opens a photo with all detected faces highlighted.
    Click a face to name it; after naming, tag suggestions are offered.
    """

    people_changed = pyqtSignal()   # emit when any face is assigned

    def __init__(self, session, file_record: dict, parent=None):
        super().__init__(parent)
        self._session     = session
        self._file_record = file_record
        self._filepath    = file_record["filepath"]
        self._file_id     = file_record["id"]

        self.setWindowTitle(f"Review faces — {file_record.get('filename', '')}")
        self.setMinimumSize(760, 560)
        self.setStyleSheet("""
            QDialog  { background: #1e1e1e; color: #d4d4d4; }
            QLabel   { color: #d4d4d4; }
            QPushButton {
                background: #3a3a3a; color: #d4d4d4; border: 1px solid #555;
                border-radius: 4px; padding: 5px 14px;
            }
            QPushButton:hover    { background: #4a4a4a; }
            QPushButton:disabled { color: #555; border-color: #333; }
            QPushButton#primary  { background: #7c6af7; border-color: #7c6af7; color: #fff; }
            QPushButton#primary:hover { background: #9480ff; }
        """)

        self._build_ui()
        self._load_detections()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Photo view
        self._photo = _PhotoFaceView()
        self._photo.face_clicked.connect(self._on_face_clicked)
        root.addWidget(self._photo, stretch=1)

        # Bottom bar
        bar = QWidget()
        bar.setStyleSheet("background: #252526; border-top: 1px solid #333;")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 8, 12, 8)
        bar_layout.setSpacing(8)

        self._status_lbl = QLabel("Click a face to assign a name")
        self._status_lbl.setStyleSheet("color:#9a9a9a; font-size:12px;")
        bar_layout.addWidget(self._status_lbl, stretch=1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bar_layout.addWidget(close_btn)

        root.addWidget(bar)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load_detections(self):
        from memoria.database.models import FaceDetection, Person
        dets = (
            self._session.query(FaceDetection)
            .filter(FaceDetection.file_id == self._file_id)
            .all()
        )
        self._detections = {
            d.id: {
                "id":       d.id,
                "bbox_x":   d.bbox_x or 0,
                "bbox_y":   d.bbox_y or 0,
                "bbox_w":   d.bbox_w or 0,
                "bbox_h":   d.bbox_h or 0,
                "name":     d.person.name if d.person else None,
                "person_id": d.person_id,
            }
            for d in dets
        }

        if not self._detections:
            self._status_lbl.setText("No face detections found for this photo.")

        self._photo.load(self._filepath, list(self._detections.values()))
        self._refresh_status()

    def _known_people(self) -> list[str]:
        from memoria.database.models import Person
        return [p.name for p in self._session.query(Person).order_by(Person.name).all()]

    def _refresh_status(self):
        total   = len(self._detections)
        unnamed = sum(1 for d in self._detections.values() if not d["name"])
        named   = total - unnamed

        if total == 0:
            self._status_lbl.setText("No face detections on this photo.")
        elif unnamed == 0:
            self._status_lbl.setText(f"✔ All {total} face{'s' if total!=1 else ''} named.")
        else:
            self._status_lbl.setText(
                f"{named}/{total} named — click an orange face to assign a name"
            )

    # ── Face click handler ────────────────────────────────────────────────────

    def _on_face_clicked(self, det_id: int):
        det = self._detections.get(det_id)
        if not det:
            return

        picker = _NamePickerDialog(self._known_people(), parent=self)
        # Pre-select if already named
        if det["name"]:
            idx = picker._combo.findText(det["name"])
            if idx >= 0:
                picker._combo.setCurrentIndex(idx)

        if picker.exec() != QDialog.DialogCode.Accepted:
            return

        name = picker.chosen_name()
        if not name:
            return

        self._assign_name(det_id, name)

    def _assign_name(self, det_id: int, name: str):
        from memoria.faces.clustering import assign_cluster_to_person
        from memoria.database.models import FaceDetection, Person, FilePeople

        det_row = self._session.query(FaceDetection).get(det_id)
        if not det_row:
            return

        # Get or create person
        person = self._session.query(Person).filter_by(name=name).first()
        if person is None:
            person = Person(name=name)
            self._session.add(person)
            self._session.flush()

        # Assign this specific detection
        det_row.person_id = person.id

        # Upsert FilePeople
        fp = (
            self._session.query(FilePeople)
            .filter_by(file_id=self._file_id, person_id=person.id)
            .first()
        )
        if fp is None:
            self._session.add(FilePeople(
                file_id=self._file_id,
                person_id=person.id,
                confidence_score=det_row.face_confidence,
            ))

        # Auto-apply a tag matching the person's name (silent, no prompt)
        self._apply_tags([name])

        self._session.commit()
        self._sync_exif()

        # Update in-memory state
        self._detections[det_id]["name"]      = name
        self._detections[det_id]["person_id"] = person.id
        self._photo.refresh_detections(list(self._detections.values()))
        self._refresh_status()
        self.people_changed.emit()

    # ── Tag helpers ───────────────────────────────────────────────────────────

    def _sync_exif(self):
        """Write the full current tag set for this photo to EXIF/IPTC."""
        try:
            from memoria.database.models import FileTag, Tag
            from memoria.exif_writer import write_tags_to_file
            rows = (
                self._session.query(Tag.label)
                .join(FileTag, FileTag.tag_id == Tag.id)
                .filter(FileTag.file_id == self._file_id)
                .order_by(Tag.label)
                .all()
            )
            write_tags_to_file(self._filepath, [r.label for r in rows])
        except Exception as e:
            log.warning(f"Could not sync tags to file after face assignment: {e}")

    def _apply_tags(self, tag_labels: list[str]):
        from memoria.database.models import FileTag, Tag
        for label in tag_labels:
            tag = self._session.query(Tag).filter_by(label=label).first()
            if tag is None:
                tag = Tag(label=label)
                self._session.add(tag)
                self._session.flush()
            existing = (
                self._session.query(FileTag)
                .filter_by(file_id=self._file_id, tag_id=tag.id)
                .first()
            )
            if not existing:
                self._session.add(FileTag(file_id=self._file_id, tag_id=tag.id))
        self._session.commit()

