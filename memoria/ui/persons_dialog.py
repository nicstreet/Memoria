"""
Persons Dialog
──────────────
Browse every named person, review all face crops assigned to them,
rename people, and remove incorrect face assignments.
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

log = logging.getLogger(__name__)

CROP_SIZE   = 120   # px — face card thumbnail size
CARD_WIDTH  = 140
CARDS_PER_ROW = 4

# ── Helpers ───────────────────────────────────────────────────────────────────

def _crop_face(filepath: str, bbox_x: int, bbox_y: int,
               bbox_w: int, bbox_h: int, size: int = CROP_SIZE) -> QPixmap | None:
    """Crop the face region from the original image and return a square QPixmap."""
    try:
        from PIL import Image
        with Image.open(filepath) as img:
            # Apply EXIF orientation
            try:
                from PIL.ExifTags import TAGS
                exif = img._getexif() or {}
                orient_tag = next((k for k, v in TAGS.items() if v == "Orientation"), None)
                orientation = exif.get(orient_tag, 1) if orient_tag else 1
                ops = {3: Image.ROTATE_180, 6: Image.ROTATE_270, 8: Image.ROTATE_90}
                if orientation in ops:
                    img = img.transpose(ops[orientation])
            except Exception:
                pass

            # Add padding around the face
            pad  = int(max(bbox_w, bbox_h) * 0.25)
            left = max(0, bbox_x - pad)
            top  = max(0, bbox_y - pad)
            right  = min(img.width,  bbox_x + bbox_w + pad)
            bottom = min(img.height, bbox_y + bbox_h + pad)

            face = img.crop((left, top, right, bottom))
            face = face.resize((size, size), Image.LANCZOS)

            buf = BytesIO()
            face.convert("RGB").save(buf, format="JPEG", quality=90)
            buf.seek(0)
            qimg = QImage.fromData(buf.read())
            return QPixmap.fromImage(qimg)
    except Exception as e:
        log.debug(f"Could not crop face from {filepath}: {e}")
        return None


def _placeholder(size: int = CROP_SIZE) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.darkGray)
    return px


# ── Face card widget ──────────────────────────────────────────────────────────

class _FaceCard(QWidget):
    """Displays a single face crop with filename and a Remove button."""

    remove_requested = pyqtSignal(int)   # detection id

    def __init__(self, det_id: int, pixmap: QPixmap,
                 filename: str, confidence: float | None, parent=None):
        super().__init__(parent)
        self.det_id = det_id
        self.setFixedWidth(CARD_WIDTH)
        self.setStyleSheet("""
            QWidget { background: #2a2a2a; border-radius: 6px; }
            QLabel  { background: transparent; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Face image
        img_lbl = QLabel()
        img_lbl.setFixedSize(CROP_SIZE, CROP_SIZE)
        img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_lbl.setPixmap(pixmap)
        img_lbl.setStyleSheet("border-radius: 4px; background: #1a1a1a;")
        layout.addWidget(img_lbl)

        # Filename (truncated)
        max_chars = CARD_WIDTH // 8
        short = filename if len(filename) <= max_chars else filename[:max_chars - 1] + "…"
        name_lbl = QLabel(short)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet("color: #aaa; font-size: 10px;")
        name_lbl.setToolTip(filename)
        layout.addWidget(name_lbl)

        # Confidence
        if confidence is not None:
            conf_lbl = QLabel(f"{confidence:.0%}")
            conf_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            conf_lbl.setStyleSheet("color: #666; font-size: 9px;")
            layout.addWidget(conf_lbl)

        # Remove button
        rm_btn = QPushButton("✕  Remove")
        rm_btn.setStyleSheet("""
            QPushButton {
                background: #3a2a2a; color: #f38ba8; border: 1px solid #5a3a3a;
                border-radius: 4px; font-size: 10px; padding: 3px;
            }
            QPushButton:hover { background: #5a2a2a; }
        """)
        rm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rm_btn.clicked.connect(lambda: self.remove_requested.emit(self.det_id))
        layout.addWidget(rm_btn)


# ── Main dialog ───────────────────────────────────────────────────────────────

class PersonsDialog(QDialog):
    """Browse, rename, and clean up named persons and their face assignments."""

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self._session = session
        self.setWindowTitle("People")
        self.resize(760, 580)
        self.setMinimumSize(500, 400)
        self.setStyleSheet("""
            QDialog  { background: #1e1e1e; color: #d4d4d4; }
            QLabel   { color: #d4d4d4; }
            QComboBox {
                background: #3a3a3a; border: 1px solid #555; border-radius: 4px;
                color: #d4d4d4; padding: 4px 8px; min-width: 200px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #2d2d2d; color: #d4d4d4;
                selection-background-color: #5a4fd4; border: 1px solid #555;
            }
            QLineEdit {
                background: #3a3a3a; border: 1px solid #555; border-radius: 4px;
                color: #d4d4d4; padding: 4px 8px;
            }
            QLineEdit:focus { border-color: #7c6af7; }
            QPushButton {
                background: #3a3a3a; color: #d4d4d4; border: 1px solid #555;
                border-radius: 4px; padding: 5px 14px;
            }
            QPushButton:hover    { background: #4a4a4a; }
            QPushButton:disabled { color: #555; border-color: #333; }
            QPushButton#primary  { background: #7c6af7; border-color: #7c6af7; color: #fff; }
            QPushButton#primary:hover { background: #9480ff; }
            QPushButton#danger   { background: #3a2020; color: #f38ba8; border-color: #6a3030; }
            QPushButton#danger:hover { background: #5a2020; }
            QScrollArea { border: none; background: #1e1e1e; }
        """)

        self._build_ui()
        self._load_people()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── Person selector row ───────────────────────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(8)

        top.addWidget(QLabel("Person:"))
        self._person_combo = QComboBox()
        self._person_combo.currentIndexChanged.connect(self._on_person_changed)
        top.addWidget(self._person_combo)

        self._face_count_lbl = QLabel("")
        self._face_count_lbl.setStyleSheet("color: #777; font-size: 11px;")
        top.addWidget(self._face_count_lbl)
        top.addStretch()

        root.addLayout(top)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        root.addWidget(sep)

        # ── Rename row ────────────────────────────────────────────────────────
        rename_row = QHBoxLayout()
        rename_row.setSpacing(8)
        rename_row.addWidget(QLabel("Rename to:"))

        self._rename_input = QLineEdit()
        self._rename_input.setPlaceholderText("New name…")
        self._rename_input.setMaximumWidth(220)
        self._rename_input.returnPressed.connect(self._on_rename)
        rename_row.addWidget(self._rename_input)

        rename_btn = QPushButton("Rename")
        rename_btn.setObjectName("primary")
        rename_btn.clicked.connect(self._on_rename)
        rename_row.addWidget(rename_btn)

        rename_row.addSpacing(24)

        delete_btn = QPushButton("🗑  Delete person")
        delete_btn.setObjectName("danger")
        delete_btn.setToolTip("Remove this person and all their face assignments from the database")
        delete_btn.clicked.connect(self._on_delete_person)
        rename_row.addWidget(delete_btn)

        rename_row.addStretch()
        root.addLayout(rename_row)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color: #333;")
        root.addWidget(sep2)

        # ── Face grid (scrollable) ────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet("background: #1e1e1e;")
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setContentsMargins(0, 8, 0, 8)
        self._grid_layout.setSpacing(10)
        self._scroll.setWidget(self._grid_widget)
        root.addWidget(self._scroll, stretch=1)

        # ── Bottom bar ────────────────────────────────────────────────────────
        bot = QHBoxLayout()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bot.addStretch()
        bot.addWidget(close_btn)
        root.addLayout(bot)

    # ── Data ──────────────────────────────────────────────────────────────────

    def _load_people(self):
        """Populate the person dropdown from the DB."""
        from memoria.database.models import Person
        self._person_combo.blockSignals(True)
        self._person_combo.clear()

        persons = self._session.query(Person).order_by(Person.name).all()
        for p in persons:
            self._person_combo.addItem(p.name, p.id)

        self._person_combo.blockSignals(False)

        if self._person_combo.count():
            self._on_person_changed(0)
        else:
            self._face_count_lbl.setText("No people in database yet")
            self._clear_grid()

    def _current_person_id(self) -> int | None:
        return self._person_combo.currentData()

    def _on_person_changed(self, _index: int):
        pid = self._current_person_id()
        if pid is None:
            return
        self._rename_input.setText(self._person_combo.currentText())
        self._load_faces(pid)

    # ── Face grid ─────────────────────────────────────────────────────────────

    def _clear_grid(self):
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _load_faces(self, person_id: int):
        self._clear_grid()
        from memoria.database.models import FaceDetection, File

        dets = (
            self._session.query(FaceDetection, File.filename, File.filepath)
            .join(File, File.id == FaceDetection.file_id)
            .filter(FaceDetection.person_id == person_id)
            .order_by(FaceDetection.face_confidence.desc().nullslast())
            .all()
        )

        self._face_count_lbl.setText(
            f"{len(dets)} face{'s' if len(dets) != 1 else ''} identified"
        )

        if not dets:
            lbl = QLabel("No faces assigned to this person yet.")
            lbl.setStyleSheet("color: #666; font-size: 12px; padding: 20px;")
            self._grid_layout.addWidget(lbl, 0, 0)
            return

        # Calculate columns from dialog width
        available = max(self._scroll.width() - 20, CARD_WIDTH * CARDS_PER_ROW)
        cols = max(1, available // (CARD_WIDTH + 10))

        row = col = 0
        for det, filename, filepath in dets:
            px = None
            if (det.bbox_x is not None and det.bbox_y is not None
                    and det.bbox_w and det.bbox_h
                    and Path(filepath).exists()):
                px = _crop_face(filepath, det.bbox_x, det.bbox_y,
                                det.bbox_w, det.bbox_h)
            if px is None:
                px = _placeholder()

            card = _FaceCard(det.id, px, filename, det.face_confidence)
            card.remove_requested.connect(self._on_remove_face)
            self._grid_layout.addWidget(card, row, col)

            col += 1
            if col >= cols:
                col = 0
                row += 1

        # Push cards to top-left
        self._grid_layout.setRowStretch(row + 1, 1)
        self._grid_layout.setColumnStretch(cols, 1)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_rename(self):
        pid = self._current_person_id()
        if pid is None:
            return
        new_name = self._rename_input.text().strip()
        if not new_name:
            return
        old_name = self._person_combo.currentText()
        if new_name == old_name:
            return

        # Check for name clash
        from memoria.database.models import Person, Tag, FileTag
        existing = self._session.query(Person).filter_by(name=new_name).first()
        if existing and existing.id != pid:
            QMessageBox.warning(self, "Name taken",
                                f"A person named '{new_name}' already exists.")
            return

        try:
            person = self._session.query(Person).get(pid)
            person.name = new_name

            # Rename the auto-tag: find Tag(old_name) linked to this person's files
            # and rename it to new_name, merging with an existing new_name tag if needed
            old_tag = self._session.query(Tag).filter_by(label=old_name).first()
            if old_tag:
                new_tag = self._session.query(Tag).filter_by(label=new_name).first()
                if new_tag:
                    # Merge: re-point old FileTag rows to the new tag, drop old tag
                    (self._session.query(FileTag)
                     .filter_by(tag_id=old_tag.id)
                     .update({"tag_id": new_tag.id}))
                    self._session.delete(old_tag)
                else:
                    old_tag.label = new_name

            self._session.commit()

            # Update combo
            idx = self._person_combo.currentIndex()
            self._person_combo.setItemText(idx, new_name)
            self._rename_input.setText(new_name)
            self._person_combo.model().sort(0)

        except Exception as e:
            self._session.rollback()
            QMessageBox.critical(self, "Rename failed", str(e))

    def _on_remove_face(self, det_id: int):
        """Unassign a single FaceDetection from this person."""
        pid = self._current_person_id()
        if pid is None:
            return
        from memoria.database.models import FaceDetection, FilePeople
        try:
            det = self._session.query(FaceDetection).get(det_id)
            if not det:
                return

            file_id  = det.file_id
            det.person_id   = None
            det.cluster_id  = None   # remove from cluster too — force re-cluster

            # Check if this was the last detection of this person in this file
            remaining = (
                self._session.query(FaceDetection)
                .filter(FaceDetection.file_id == file_id,
                        FaceDetection.person_id == pid,
                        FaceDetection.id != det_id)
                .count()
            )
            if remaining == 0:
                # Remove FilePeople link
                (self._session.query(FilePeople)
                 .filter_by(file_id=file_id, person_id=pid)
                 .delete())
                # Remove the person-name tag from this file
                self._remove_person_tag(file_id, pid)

            self._session.commit()

            # Remove the card from the grid
            for i in range(self._grid_layout.count()):
                item = self._grid_layout.itemAt(i)
                if item and isinstance(item.widget(), _FaceCard):
                    if item.widget().det_id == det_id:
                        w = self._grid_layout.takeAt(i).widget()
                        w.deleteLater()
                        break

            # Update count
            current = self._face_count_lbl.text()
            try:
                n = int(current.split()[0]) - 1
                self._face_count_lbl.setText(
                    f"{n} face{'s' if n != 1 else ''} identified"
                )
            except Exception:
                pass

        except Exception as e:
            self._session.rollback()
            QMessageBox.critical(self, "Remove failed", str(e))

    def _remove_person_tag(self, file_id: int, person_id: int):
        """Remove the person-name tag from a file (if it was auto-applied)."""
        from memoria.database.models import Person, Tag, FileTag
        person = self._session.query(Person).get(person_id)
        if not person:
            return
        tag = self._session.query(Tag).filter_by(label=person.name).first()
        if tag:
            (self._session.query(FileTag)
             .filter_by(file_id=file_id, tag_id=tag.id)
             .delete())

    def _on_delete_person(self):
        pid = self._current_person_id()
        if pid is None:
            return
        name = self._person_combo.currentText()

        reply = QMessageBox.question(
            self, "Delete person",
            f"Delete <b>{name}</b> and remove all their face assignments?<br><br>"
            "This will unassign all their detections and remove their name tag "
            "from every photo. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        from memoria.database.models import Person, FaceDetection, FilePeople, Tag, FileTag
        try:
            # Unassign all detections
            (self._session.query(FaceDetection)
             .filter_by(person_id=pid)
             .update({"person_id": None, "cluster_id": None}))

            # Remove all FilePeople rows
            (self._session.query(FilePeople)
             .filter_by(person_id=pid)
             .delete())

            # Remove person-name tag from all files
            tag = self._session.query(Tag).filter_by(label=name).first()
            if tag:
                self._session.query(FileTag).filter_by(tag_id=tag.id).delete()
                self._session.delete(tag)

            # Delete person record
            person = self._session.query(Person).get(pid)
            if person:
                self._session.delete(person)

            self._session.commit()

            # Remove from combo and reload
            idx = self._person_combo.currentIndex()
            self._person_combo.removeItem(idx)
            if self._person_combo.count():
                self._on_person_changed(self._person_combo.currentIndex())
            else:
                self._clear_grid()
                self._face_count_lbl.setText("No people in database yet")

        except Exception as e:
            self._session.rollback()
            QMessageBox.critical(self, "Delete failed", str(e))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Re-flow the grid when the dialog is resized
        pid = self._current_person_id()
        if pid is not None:
            self._load_faces(pid)
