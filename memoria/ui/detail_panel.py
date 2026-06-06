from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFrame, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from memoria.ui.thumbnail_cache import ThumbnailCache, _square_crop


class DetailPanel(QWidget):
    def __init__(self, thumbnail_cache: ThumbnailCache, parent=None):
        super().__init__(parent)
        self.setObjectName("detailPanel")
        self.setMinimumWidth(220)
        self.setMaximumWidth(340)
        self._cache = thumbnail_cache
        self._current_record: dict | None = None
        self._current_meta: dict | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Large thumbnail preview
        self._thumb_label = QLabel()
        self._thumb_label.setFixedSize(256, 256)
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setStyleSheet("background:#1a1a1a; border-radius:4px;")
        layout.addWidget(self._thumb_label)

        # Filename
        self._title = QLabel("Select a photo")
        self._title.setObjectName("detailTitle")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #444;")
        layout.addWidget(separator)

        # Scrollable metadata area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        meta_widget = QWidget()
        meta_widget.setStyleSheet("background: transparent;")
        self._meta_layout = QVBoxLayout(meta_widget)
        self._meta_layout.setContentsMargins(0, 0, 0, 0)
        self._meta_layout.setSpacing(4)
        self._meta_layout.addStretch()

        scroll.setWidget(meta_widget)
        layout.addWidget(scroll, stretch=1)

        # Open file button
        self._open_btn = QPushButton("Open in default app")
        self._open_btn.setEnabled(False)
        self._open_btn.clicked.connect(self._open_file)
        layout.addWidget(self._open_btn)

    # ── Public API ───────────────────────────────────────────────────────────

    def show_file(self, record: dict, meta: dict | None = None):
        """Populate the panel with file data. meta is the Metadata row as a dict."""
        self._current_record = record
        self._current_meta = meta

        # Thumbnail
        px = self._cache.get(record["id"], record["filepath"], record["file_type"])
        self._thumb_label.setPixmap(
            px.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)
        )

        # Title
        self._title.setText(record.get("filename", ""))

        # Rebuild metadata rows
        self._clear_meta()
        self._add_meta("Type", record.get("file_type", "").capitalize())
        if record.get("date_taken"):
            self._add_meta("Date taken", record["date_taken"].strftime("%Y-%m-%d %H:%M"))

        if meta:
            if meta.get("camera_make") or meta.get("camera_model"):
                camera = " ".join(filter(None, [meta.get("camera_make"), meta.get("camera_model")]))
                self._add_meta("Camera", camera)
            if meta.get("width") and meta.get("height"):
                self._add_meta("Dimensions", f"{meta['width']} × {meta['height']} px")
            if meta.get("duration_seconds"):
                secs = int(meta["duration_seconds"])
                self._add_meta("Duration", f"{secs // 60}m {secs % 60}s")
            if meta.get("location_label"):
                self._add_meta("Location", meta["location_label"])
            elif meta.get("gps_lat"):
                self._add_meta("GPS", f"{meta['gps_lat']:.4f}, {meta['gps_lon']:.4f}")

        # File size
        try:
            size = Path(record["filepath"]).stat().st_size
            self._add_meta("File size", _fmt_size(size))
        except OSError:
            pass

        self._add_meta("Path", record.get("filepath", ""), small=True)
        self._open_btn.setEnabled(True)

    def clear(self):
        self._current_record = None
        self._thumb_label.clear()
        self._thumb_label.setStyleSheet("background:#1a1a1a; border-radius:4px;")
        self._title.setText("Select a photo")
        self._clear_meta()
        self._open_btn.setEnabled(False)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _clear_meta(self):
        while self._meta_layout.count() > 1:  # keep the stretch at the end
            item = self._meta_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_meta(self, label: str, value: str, small: bool = False):
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        v = QVBoxLayout(row)
        v.setContentsMargins(0, 2, 0, 2)
        v.setSpacing(1)

        lbl = QLabel(label.upper())
        lbl.setStyleSheet("color:#666; font-size:10px; font-weight:bold; letter-spacing:0.5px;")
        v.addWidget(lbl)

        val = QLabel(value)
        val.setWordWrap(True)
        val.setStyleSheet(f"color:#d4d4d4; font-size:{'11' if small else '12'}px;")
        v.addWidget(val)

        self._meta_layout.insertWidget(self._meta_layout.count() - 1, row)

    def _open_file(self):
        if self._current_record:
            filepath = self._current_record.get("filepath", "")
            if filepath and Path(filepath).exists():
                os.startfile(filepath)


def _fmt_size(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"
