from __future__ import annotations

import logging
import os
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from memoria.database.db import get_session
from memoria.database.models import Duplicate, File, Metadata

log = logging.getLogger(__name__)

PREVIEW_SIZE = 300


def _load_pixmap(filepath: str, size: int) -> QPixmap:
    """Load and scale a pixmap, applying EXIF orientation."""
    try:
        from PIL import Image
        import io
        with Image.open(filepath) as img:
            img = img.convert("RGB")
            try:
                import exifread
                with open(filepath, "rb") as f:
                    tags = exifread.process_file(f, stop_tag="Image Orientation", details=False)
                tag = tags.get("Image Orientation")
                if tag and tag.values:
                    val = int(str(tag.values[0]))
                    rotations = {3: 180, 6: 270, 8: 90}
                    if val in rotations:
                        img = img.rotate(rotations[val], expand=True)
            except Exception:
                pass
            img.thumbnail((size, size))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
        px = QPixmap()
        px.loadFromData(buf.getvalue())
        return px
    except Exception:
        px = QPixmap(size, size)
        px.fill(Qt.GlobalColor.darkGray)
        return px


def _fmt_size(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


class _FilePanel(QWidget):
    """Shows one file in a duplicate pair — preview + metadata + action buttons."""

    keep_clicked = pyqtSignal()
    trash_clicked = pyqtSignal()
    open_clicked = pyqtSignal()

    def __init__(self, file_row: File, meta_row: Metadata | None, parent=None):
        super().__init__(parent)
        self.file_row = file_row
        self.setStyleSheet("background: #2d2d2d; border-radius: 6px;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Preview image
        self._img_lbl = QLabel()
        self._img_lbl.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background:#1a1a1a; border-radius:4px;")
        layout.addWidget(self._img_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Load preview
        px = _load_pixmap(file_row.filepath, PREVIEW_SIZE)
        if not px.isNull():
            self._img_lbl.setPixmap(
                px.scaled(PREVIEW_SIZE, PREVIEW_SIZE,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )

        # Metadata
        self._add_info("Filename", file_row.filename)
        if meta_row and meta_row.date_taken:
            self._add_info("Date taken", meta_row.date_taken.strftime("%Y-%m-%d  %H:%M"))
        if meta_row and meta_row.width and meta_row.height:
            self._add_info("Dimensions", f"{meta_row.width} × {meta_row.height} px")
        try:
            size = Path(file_row.filepath).stat().st_size
            self._add_info("File size", _fmt_size(size))
        except OSError:
            pass
        self._add_info("Path", file_row.filepath, small=True)

        layout.addStretch()

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        keep_btn = QPushButton("✓  Keep")
        keep_btn.setStyleSheet("""
            QPushButton {
                background: #2d5a2d; border: 1px solid #4a8a4a;
                border-radius: 4px; color: #8fdf8f; padding: 5px 12px;
            }
            QPushButton:hover { background: #3a6e3a; }
        """)
        keep_btn.clicked.connect(self.keep_clicked)
        btn_row.addWidget(keep_btn)

        trash_btn = QPushButton("🗑  Move to trash")
        trash_btn.setStyleSheet("""
            QPushButton {
                background: #5a2d2d; border: 1px solid #8a4a4a;
                border-radius: 4px; color: #df8f8f; padding: 5px 12px;
            }
            QPushButton:hover { background: #6e3a3a; }
        """)
        trash_btn.clicked.connect(self.trash_clicked)
        btn_row.addWidget(trash_btn)

        open_btn = QPushButton("Open")
        open_btn.setStyleSheet("""
            QPushButton {
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; color: #d4d4d4; padding: 5px 8px;
            }
            QPushButton:hover { background: #4a4a4a; }
        """)
        open_btn.clicked.connect(self.open_clicked)
        btn_row.addWidget(open_btn)

        layout.addLayout(btn_row)

    def _add_info(self, label: str, value: str, small: bool = False):
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        v = QVBoxLayout(row)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        lbl = QLabel(label)
        lbl.setStyleSheet("color:#555; font-size:10px; font-weight:bold;")
        v.addWidget(lbl)
        val = QLabel(value)
        val.setWordWrap(True)
        val.setStyleSheet(f"color:#d4d4d4; font-size:{'10' if small else '11'}px;")
        v.addWidget(val)
        self.layout().addWidget(row)

    def mark_kept(self):
        self.setStyleSheet("background: #1e3a1e; border-radius: 6px; border: 1px solid #4a8a4a;")

    def mark_trashed(self):
        self.setStyleSheet("background: #3a1e1e; border-radius: 6px; border: 1px solid #8a4a4a;")


class _PairWidget(QWidget):
    """Side-by-side comparison of one duplicate pair."""

    resolved = pyqtSignal()

    def __init__(self, dup: Duplicate, file_a: File, meta_a: Metadata | None,
                 file_b: File, meta_b: Metadata | None, parent=None):
        super().__init__(parent)
        self._dup = dup
        self._session = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Distance badge
        raw = dup.hash_distance
        if isinstance(raw, (bytes, bytearray)):
            import struct
            distance = struct.unpack_from('<q', raw.ljust(8, b'\x00'))[0]
        else:
            distance = int(raw)

        # MD5 comparison for definitive identical check
        from memoria.indexer.hashing import compute_md5
        md5_a = compute_md5(file_a.filepath)
        md5_b = compute_md5(file_b.filepath)
        if md5_a and md5_b:
            if md5_a == md5_b:
                match_str = "✓ Files are byte-for-byte identical (same MD5)"
                match_colour = "#8fdf8f"
            else:
                match_str = "≈ Visually similar but different files (different MD5)"
                match_colour = "#dfb48f"
        else:
            match_str = ""
            match_colour = "#888"

        dist_lbl = QLabel(
            f"Perceptual hash distance: {distance}  "
            f"({'Identical' if distance == 0 else 'Very similar' if distance <= 5 else 'Similar'})"
        )
        dist_lbl.setStyleSheet("color:#888; font-size:11px;")
        layout.addWidget(dist_lbl)

        # Side by side panels
        panels_row = QHBoxLayout()
        panels_row.setSpacing(12)

        self._panel_a = _FilePanel(file_a, meta_a)
        self._panel_b = _FilePanel(file_b, meta_b)

        self._panel_a.keep_clicked.connect(lambda: self._resolve("keep_a"))
        self._panel_a.trash_clicked.connect(lambda: self._resolve("trash_a"))
        self._panel_a.open_clicked.connect(lambda: os.startfile(file_a.filepath))

        self._panel_b.keep_clicked.connect(lambda: self._resolve("keep_b"))
        self._panel_b.trash_clicked.connect(lambda: self._resolve("trash_b"))
        self._panel_b.open_clicked.connect(lambda: os.startfile(file_b.filepath))

        panels_row.addWidget(self._panel_a)
        panels_row.addWidget(self._panel_b)
        layout.addLayout(panels_row)

        # Keep both option
        both_row = QHBoxLayout()
        keep_both = QPushButton("Keep both — not duplicates")
        keep_both.setStyleSheet("""
            QPushButton {
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; color: #aaa; padding: 4px 12px; font-size:11px;
            }
            QPushButton:hover { background: #4a4a4a; }
        """)
        keep_both.clicked.connect(lambda: self._resolve("keep_both"))
        both_row.addStretch()
        both_row.addWidget(keep_both)
        both_row.addStretch()
        layout.addLayout(both_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        layout.addWidget(sep)

    def set_session(self, session):
        self._session = session

    def _resolve(self, action: str):
        if not self._session:
            return
        try:
            if action == "trash_a":
                self._send_to_trash(self._panel_a.file_row.filepath)
                self._panel_a.mark_trashed()
                self._panel_b.mark_kept()
            elif action == "trash_b":
                self._send_to_trash(self._panel_b.file_row.filepath)
                self._panel_b.mark_trashed()
                self._panel_a.mark_kept()
            elif action == "keep_a":
                self._panel_a.mark_kept()
                self._panel_b.mark_trashed()
            elif action == "keep_b":
                self._panel_b.mark_kept()
                self._panel_a.mark_trashed()

            # Mark as reviewed in DB
            self._dup.reviewed = True
            self._session.commit()
            self.resolved.emit()

            # Disable all buttons
            for panel in (self._panel_a, self._panel_b):
                for btn in panel.findChildren(QPushButton):
                    if btn.text() != "Open":
                        btn.setEnabled(False)

        except Exception as e:
            log.error(f"Duplicate resolution failed: {e}", exc_info=True)
            QMessageBox.warning(self.parent(), "Error", str(e))

    def _send_to_trash(self, filepath: str):
        """Send file to Windows Recycle Bin."""
        try:
            from send2trash import send2trash
            send2trash(filepath)
        except ImportError:
            # Fallback: move to a Memoria trash folder
            trash_dir = Path(filepath).parent / ".memoria_trash"
            trash_dir.mkdir(exist_ok=True)
            Path(filepath).rename(trash_dir / Path(filepath).name)
            log.info(f"Moved to local trash: {filepath}")


class DuplicateReviewDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review Duplicates")
        self.setMinimumSize(900, 700)
        self.setStyleSheet("""
            QDialog { background: #1e1e1e; color: #d4d4d4; }
            QScrollArea { border: none; background: #1e1e1e; }
        """)
        self._session = get_session()
        self._build_ui()
        self._load_pairs()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Duplicate Review")
        title.setStyleSheet("font-size:16px; font-weight:bold; color:#fff;")
        layout.addWidget(title)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#888; font-size:12px;")
        layout.addWidget(self._status)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#333;")
        layout.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._pairs_widget = QWidget()
        self._pairs_widget.setStyleSheet("background: transparent;")
        self._pairs_layout = QVBoxLayout(self._pairs_widget)
        self._pairs_layout.setContentsMargins(0, 0, 0, 0)
        self._pairs_layout.setSpacing(16)
        self._pairs_layout.addStretch()
        scroll.setWidget(self._pairs_widget)
        layout.addWidget(scroll, stretch=1)

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet("""
            QPushButton {
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; color: #d4d4d4; padding: 5px 12px;
            }
            QPushButton:hover { background: #4a4a4a; }
        """)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _load_pairs(self):
        pairs = (
            self._session.query(Duplicate)
            .filter(Duplicate.reviewed == False)
            .order_by(Duplicate.hash_distance)
            .all()
        )

        reviewed = (
            self._session.query(Duplicate)
            .filter(Duplicate.reviewed == True)
            .count()
        )

        total = len(pairs) + reviewed
        self._status.setText(
            f"{len(pairs)} pair{'s' if len(pairs) != 1 else ''} to review  •  "
            f"{reviewed} of {total} already reviewed"
        )

        if not pairs:
            lbl = QLabel("No unreviewed duplicate pairs. Run the indexer to detect new duplicates.")
            lbl.setStyleSheet("color:#555; font-size:13px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._pairs_layout.insertWidget(0, lbl)
            return

        for dup in pairs:
            file_a = self._session.query(File).get(dup.file_id_a)
            file_b = self._session.query(File).get(dup.file_id_b)
            if not file_a or not file_b:
                continue
            meta_a = self._session.query(Metadata).filter_by(file_id=file_a.id).first()
            meta_b = self._session.query(Metadata).filter_by(file_id=file_b.id).first()

            pair_widget = _PairWidget(dup, file_a, meta_a, file_b, meta_b)
            pair_widget.set_session(self._session)
            self._pairs_layout.insertWidget(
                self._pairs_layout.count() - 1, pair_widget
            )

    def closeEvent(self, event):
        self._session.close()
        super().closeEvent(event)
