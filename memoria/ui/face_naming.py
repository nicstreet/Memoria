from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from memoria.database.db import get_session
from memoria.database.models import FaceDetection, Person, FilePeople

log = logging.getLogger(__name__)

CROP_SIZE = 80   # face crop thumbnail size in pixels


def _crop_face(filepath: str, bbox: dict) -> QPixmap | None:
    """Crop the face region from an image and return as QPixmap."""
    try:
        from PIL import Image
        with Image.open(filepath) as img:
            img = img.convert("RGB")
            # Apply EXIF orientation
            try:
                import exifread
                with open(filepath, "rb") as f:
                    tags = exifread.process_file(f, stop_tag="Image Orientation", details=False)
                tag = tags.get("Image Orientation")
                if tag and tag.values:
                    val = tag.values[0]
                    from PIL import ImageOps
                    orientations = {3: 180, 6: 270, 8: 90}
                    if int(str(val)) in orientations:
                        img = img.rotate(orientations[int(str(val))], expand=True)
            except Exception:
                pass

            x = bbox.get("bbox_x") or 0
            y = bbox.get("bbox_y") or 0
            w = bbox.get("bbox_w") or 100
            h = bbox.get("bbox_h") or 100
            # Add 20% padding around the face
            pad_x = int(w * 0.2)
            pad_y = int(h * 0.2)
            x1 = max(0, x - pad_x)
            y1 = max(0, y - pad_y)
            x2 = min(img.width,  x + w + pad_x)
            y2 = min(img.height, y + h + pad_y)
            cropped = img.crop((x1, y1, x2, y2))
            cropped = cropped.resize((CROP_SIZE, CROP_SIZE))
            import io
            buf = io.BytesIO()
            cropped.save(buf, format="JPEG")
            img_data = buf.getvalue()
        px = QPixmap()
        px.loadFromData(img_data)
        return px if not px.isNull() else None
    except Exception as e:
        log.warning(f"Face crop failed: {e}")
        return None


class _ClusterCard(QWidget):
    """Card showing sample face crops for one cluster with a name input."""

    name_confirmed = pyqtSignal(int, str)   # cluster_id, name
    skipped = pyqtSignal(int)               # cluster_id

    def __init__(self, cluster_id: int, face_count: int,
                 samples: list[FaceDetection], parent=None):
        super().__init__(parent)
        self.cluster_id = cluster_id
        self.setStyleSheet("background: #2d2d2d; border-radius: 6px;")
        self.setFixedWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header
        hdr = QLabel(f"Cluster {cluster_id + 1}  —  {face_count} photo{'s' if face_count != 1 else ''}")
        hdr.setStyleSheet("color:#aaa; font-size:11px;")
        layout.addWidget(hdr)

        # Face crops row
        crops_row = QHBoxLayout()
        crops_row.setSpacing(6)
        shown = 0
        for det in samples[:5]:
            bbox = {
                "bbox_x": det.bbox_x, "bbox_y": det.bbox_y,
                "bbox_w": det.bbox_w, "bbox_h": det.bbox_h,
            }
            px = _crop_face(det.file.filepath, bbox) if det.file else None
            lbl = QLabel()
            lbl.setFixedSize(CROP_SIZE, CROP_SIZE)
            lbl.setStyleSheet("background:#1a1a1a; border-radius:4px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if px:
                lbl.setPixmap(px)
            else:
                lbl.setText("?")
                lbl.setStyleSheet("background:#1a1a1a; border-radius:4px; color:#555;")
            crops_row.addWidget(lbl)
            shown += 1
        crops_row.addStretch()
        layout.addLayout(crops_row)

        # Name input
        name_row = QHBoxLayout()
        name_row.setSpacing(6)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Enter name…")
        self._name_input.setStyleSheet("""
            QLineEdit {
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; color: #d4d4d4; padding: 4px 8px;
            }
            QLineEdit:focus { border-color: #7c6af7; }
        """)
        self._name_input.returnPressed.connect(self._confirm)
        name_row.addWidget(self._name_input)

        confirm_btn = QPushButton("Confirm")
        confirm_btn.setStyleSheet("""
            QPushButton {
                background: #7c6af7; border: none; border-radius: 4px;
                color: #fff; padding: 4px 12px;
            }
            QPushButton:hover { background: #9480ff; }
        """)
        confirm_btn.clicked.connect(self._confirm)
        name_row.addWidget(confirm_btn)

        skip_btn = QPushButton("Skip")
        skip_btn.setStyleSheet("""
            QPushButton {
                background: #3a3a3a; border: 1px solid #555;
                border-radius: 4px; color: #888; padding: 4px 8px;
            }
            QPushButton:hover { background: #4a4a4a; }
        """)
        skip_btn.clicked.connect(lambda: self.skipped.emit(self.cluster_id))
        name_row.addWidget(skip_btn)

        layout.addLayout(name_row)

    def _confirm(self):
        name = self._name_input.text().strip()
        if name:
            self.name_confirmed.emit(self.cluster_id, name)
        else:
            self._name_input.setFocus()


class FaceNamingDialog(QDialog):
    people_updated = pyqtSignal()   # emitted when any cluster is named

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Name Faces")
        self.setMinimumSize(800, 600)
        self.setStyleSheet("""
            QDialog { background: #1e1e1e; color: #d4d4d4; }
            QScrollArea { border: none; background: #1e1e1e; }
        """)
        self._session = get_session()
        self._build_ui()
        self._load_clusters()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        title = QLabel("Name Face Clusters")
        title.setStyleSheet("font-size:16px; font-weight:bold; color:#fff;")
        layout.addWidget(title)

        sub = QLabel(
            "Each cluster groups similar faces detected across your library. "
            "Type a name and click Confirm, or Skip to leave unnamed."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#888; font-size:12px;")
        layout.addWidget(sub)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#333;")
        layout.addWidget(sep)

        # Scrollable cluster cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._cards_widget = QWidget()
        self._cards_widget.setStyleSheet("background: transparent;")
        self._cards_layout = QGridLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(12)
        scroll.setWidget(self._cards_widget)
        layout.addWidget(scroll, stretch=1)

        # Status label
        self._status = QLabel("")
        self._status.setStyleSheet("color:#888; font-size:11px;")
        layout.addWidget(self._status)

        # Close button
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

    def _load_clusters(self):
        # Clear existing cards
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        from sqlalchemy import func
        rows = (
            self._session.query(FaceDetection.cluster_id, func.count(FaceDetection.id))
            .filter(FaceDetection.cluster_id.isnot(None),
                    FaceDetection.cluster_id >= 0)
            .group_by(FaceDetection.cluster_id)
            .order_by(func.count(FaceDetection.id).desc())
            .all()
        )

        if not rows:
            self._status.setText("No face clusters found. Run 'cluster-faces' from the CLI first.")
            return

        self._status.setText(f"{len(rows)} cluster{'s' if len(rows) != 1 else ''} found")

        col = 0
        row = 0
        for cluster_id, count in rows:
            samples = (
                self._session.query(FaceDetection)
                .filter(FaceDetection.cluster_id == cluster_id)
                .limit(5)
                .all()
            )
            # Load file relationships
            for s in samples:
                _ = s.file

            card = _ClusterCard(cluster_id, count, samples)
            card.name_confirmed.connect(self._on_name_confirmed)
            card.skipped.connect(self._on_skipped)
            self._cards_layout.addWidget(card, row, col)
            col += 1
            if col >= 2:
                col = 0
                row += 1

    def _on_name_confirmed(self, cluster_id: int, name: str):
        try:
            from memoria.faces.clustering import assign_cluster_to_person
            assign_cluster_to_person(self._session, cluster_id, name)
            self.people_updated.emit()
            # Dim the card to show it's done
            for i in range(self._cards_layout.count()):
                w = self._cards_layout.itemAt(i).widget()
                if isinstance(w, _ClusterCard) and w.cluster_id == cluster_id:
                    w.setStyleSheet("background: #1e2e1e; border-radius: 6px;")
                    w.setEnabled(False)
                    break
            log.info(f"Cluster {cluster_id} named '{name}'")
        except Exception as e:
            log.error(f"Failed to name cluster: {e}")
            QMessageBox.warning(self, "Error", f"Could not save name: {e}")

    def _on_skipped(self, cluster_id: int):
        for i in range(self._cards_layout.count()):
            w = self._cards_layout.itemAt(i).widget()
            if isinstance(w, _ClusterCard) and w.cluster_id == cluster_id:
                w.setStyleSheet("background: #252525; border-radius: 6px; opacity: 0.5;")
                w.setEnabled(False)
                break

    def closeEvent(self, event):
        self._session.close()
        super().closeEvent(event)
