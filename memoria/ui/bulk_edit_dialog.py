"""
Bulk Edit Dialog
────────────────
Apply Title, Subject, Location and/or Tags to every currently-displayed photo.

Each field has a "Apply" checkbox so only ticked fields are written.
Tag entry supports comma-separated values and offers Replace or Append mode.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFrame, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

log = logging.getLogger(__name__)

_INPUT_STYLE = """
    QLineEdit, QComboBox {
        background: #3a3a3a; border: 1px solid #555; border-radius: 4px;
        color: #d4d4d4; padding: 4px 8px; font-size: 12px;
    }
    QLineEdit:focus, QComboBox:focus { border-color: #7c6af7; }
    QLineEdit:disabled, QComboBox:disabled { color: #555; background: #2a2a2a; }
    QComboBox::drop-down { border: none; }
    QComboBox QAbstractItemView {
        background: #2d2d2d; color: #d4d4d4;
        selection-background-color: #5a4fd4; border: 1px solid #555;
    }
"""


class _FieldRow(QWidget):
    """One row: enable-checkbox | label | input widget."""

    def __init__(self, label: str, widget: QWidget, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.checkbox = QCheckBox()
        self.checkbox.setFixedWidth(18)
        self.checkbox.setToolTip(f"Apply {label} to all displayed photos")
        self.checkbox.stateChanged.connect(self._on_toggle)
        row.addWidget(self.checkbox)

        lbl = QLabel(f"{label}:")
        lbl.setFixedWidth(72)
        lbl.setStyleSheet("color:#aaa; font-size:12px;")
        row.addWidget(lbl)

        self.input = widget
        self.input.setEnabled(False)
        row.addWidget(self.input, stretch=1)

    def _on_toggle(self, state):
        self.input.setEnabled(bool(state))

    @property
    def active(self) -> bool:
        return self.checkbox.isChecked()


class BulkEditDialog(QDialog):
    """Apply metadata fields to all currently-displayed photos."""

    changes_applied = pyqtSignal()

    def __init__(self, session, records: list[dict], parent=None):
        super().__init__(parent)
        self._session = session
        self._records = records   # only the currently visible photos

        self.setWindowTitle(f"Bulk Edit — {len(records):,} photo{'s' if len(records) != 1 else ''}")
        self.setMinimumWidth(480)
        self.setStyleSheet(f"""
            QDialog   {{ background: #1e1e1e; color: #d4d4d4; }}
            QLabel    {{ color: #d4d4d4; }}
            QCheckBox {{ color: #d4d4d4; }}
            QCheckBox::indicator {{
                width: 14px; height: 14px; border-radius: 3px;
                border: 1px solid #555; background: #2a2a2a;
            }}
            QCheckBox::indicator:checked {{
                background: #7c6af7; border-color: #7c6af7;
            }}
            QProgressBar {{
                background: #2a2a2a; border: 1px solid #444;
                border-radius: 4px; height: 10px; text-align: center;
                color: transparent;
            }}
            QProgressBar::chunk {{ background: #7c6af7; border-radius: 3px; }}
            QPushButton {{
                background: #3a3a3a; color: #d4d4d4; border: 1px solid #555;
                border-radius: 4px; padding: 5px 14px;
            }}
            QPushButton:hover    {{ background: #4a4a4a; }}
            QPushButton:disabled {{ color: #555; border-color: #333; }}
            QPushButton#primary  {{ background: #7c6af7; border-color: #7c6af7; color:#fff; }}
            QPushButton#primary:hover {{ background: #9480ff; }}
            {_INPUT_STYLE}
        """)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Summary label
        photos_only = [r for r in self._records if r.get("file_type") == "photo"]
        n_total  = len(self._records)
        n_photos = len(photos_only)
        n_videos = n_total - n_photos

        summary = f"Applying to <b>{n_photos}</b> photo{'s' if n_photos != 1 else ''}"
        if n_videos:
            summary += f" ({n_videos} video{'s' if n_videos != 1 else ''} will be skipped for EXIF)"
        lbl = QLabel(summary)
        lbl.setStyleSheet("font-size:12px; color:#d4d4d4;")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#333;")
        layout.addWidget(sep)

        # ── Title ──────────────────────────────────────────────────────────
        self._title_input = QLineEdit()
        self._title_input.setPlaceholderText("Enter title…")
        self._title_row = _FieldRow("Title", self._title_input)
        layout.addWidget(self._title_row)

        # ── Subject ────────────────────────────────────────────────────────
        from memoria.ui.default_subjects import ALL_SUBJECTS, SUBJECT_CATEGORIES
        from PyQt6.QtWidgets import QCompleter, QMenu
        from PyQt6.QtCore import Qt

        subj_widget = QWidget()
        subj_widget.setStyleSheet("background:transparent;")
        subj_h = QHBoxLayout(subj_widget)
        subj_h.setContentsMargins(0, 0, 0, 0)
        subj_h.setSpacing(4)

        self._subject_input = QLineEdit()
        self._subject_input.setPlaceholderText("Enter subject…")
        _sc = QCompleter(ALL_SUBJECTS, self._subject_input)
        _sc.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        _sc.setFilterMode(Qt.MatchFlag.MatchContains)
        self._subject_input.setCompleter(_sc)
        subj_h.addWidget(self._subject_input, stretch=1)

        subj_drop = QPushButton("▾")
        subj_drop.setFixedSize(26, 26)
        subj_drop.setToolTip("Choose from default subjects")
        subj_drop.setCursor(Qt.CursorShape.PointingHandCursor)
        subj_drop.setStyleSheet(
            "QPushButton{background:#3a3a3a;border:1px solid #555;"
            "border-radius:4px;color:#aaa;font-size:11px;padding:0;}"
            "QPushButton:hover{background:#4a4a4a;color:#fff;}"
        )
        def _show_subj_menu():
            m = QMenu(self)
            m.setStyleSheet(
                "QMenu{background:#252526;color:#d4d4d4;border:1px solid #444;border-radius:4px;}"
                "QMenu::item{padding:4px 24px 4px 12px;font-size:12px;}"
                "QMenu::item:selected{background:#5a4fd4;color:#fff;}"
            )
            for cat, subjects in SUBJECT_CATEGORIES:
                sub = m.addMenu(cat)
                sub.setStyleSheet(m.styleSheet())
                for s in subjects:
                    sub.addAction(s).triggered.connect(
                        lambda checked=False, v=s: self._subject_input.setText(v)
                    )
            m.exec(subj_drop.mapToGlobal(subj_drop.rect().bottomLeft()))
        subj_drop.clicked.connect(_show_subj_menu)
        subj_h.addWidget(subj_drop)

        self._subject_row = _FieldRow("Subject", subj_widget)
        layout.addWidget(self._subject_row)

        # ── Location ───────────────────────────────────────────────────────
        self._location_input = QLineEdit()
        self._location_input.setPlaceholderText("Enter location label…")
        self._location_row = _FieldRow("Location", self._location_input)
        layout.addWidget(self._location_row)

        # ── Tags ───────────────────────────────────────────────────────────
        tag_widget = QWidget()
        tag_widget.setStyleSheet("background:transparent;")
        tag_inner = QHBoxLayout(tag_widget)
        tag_inner.setContentsMargins(0, 0, 0, 0)
        tag_inner.setSpacing(6)

        self._tags_input = QLineEdit()
        self._tags_input.setPlaceholderText("tag1, tag2, tag3…")
        tag_inner.addWidget(self._tags_input, stretch=1)

        self._tags_mode = QComboBox()
        self._tags_mode.addItem("Append", "append")
        self._tags_mode.addItem("Replace", "replace")
        self._tags_mode.setFixedWidth(90)
        tag_inner.addWidget(self._tags_mode)

        self._tags_row = _FieldRow("Tags", tag_widget)
        layout.addWidget(self._tags_row)

        hint = QLabel("Append adds to existing tags. Replace overwrites them.")
        hint.setStyleSheet("color:#666; font-size:10px; padding-left:26px;")
        layout.addWidget(hint)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#333;")
        layout.addWidget(sep2)

        # ── Progress bar (hidden until Apply) ─────────────────────────────
        self._progress = QProgressBar()
        self._progress.hide()
        layout.addWidget(self._progress)

        self._progress_lbl = QLabel("")
        self._progress_lbl.setStyleSheet("color:#777; font-size:11px;")
        self._progress_lbl.hide()
        layout.addWidget(self._progress_lbl)

        # ── Buttons ────────────────────────────────────────────────────────
        btns = QDialogButtonBox()
        self._apply_btn = btns.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        self._apply_btn.setObjectName("primary")
        cancel_btn = btns.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        btns.accepted.connect(self._apply)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ── Apply ─────────────────────────────────────────────────────────────────

    def _apply(self):
        # Gather what to do
        do_title    = self._title_row.active
        do_subject  = self._subject_row.active
        do_location = self._location_row.active
        do_tags     = self._tags_row.active

        if not any([do_title, do_subject, do_location, do_tags]):
            return

        title    = self._title_input.text().strip()
        subject  = self._subject_input.text().strip()
        location = self._location_input.text().strip()
        raw_tags = [t.strip() for t in self._tags_input.text().split(",") if t.strip()]
        tag_mode = self._tags_mode.currentData()

        self._apply_btn.setEnabled(False)
        records   = self._records
        total     = len(records)

        self._progress.setRange(0, total)
        self._progress.setValue(0)
        self._progress.show()
        self._progress_lbl.show()

        from memoria.database.models import File, Metadata, Tag, FileTag
        from memoria.exif_writer import write_tags_to_file
        from memoria.file_status import maybe_auto_rename

        changed = 0
        for i, rec in enumerate(records):
            self._progress.setValue(i + 1)
            self._progress_lbl.setText(f"Processing {rec['filename']}…")
            # Force Qt to process pending events so the bar repaints
            from PyQt6.QtWidgets import QApplication
            QApplication.processEvents()

            file_id = rec["id"]
            try:
                meta = (
                    self._session.query(Metadata)
                    .filter_by(file_id=file_id).first()
                )
                if meta is None:
                    meta = Metadata(file_id=file_id)
                    self._session.add(meta)

                if do_title:    meta.title    = title or None
                if do_subject:  meta.subject  = subject or None
                if do_location: meta.location_label = location or None

                if do_tags and raw_tags:
                    if tag_mode == "replace":
                        # Remove all existing tags for this file
                        self._session.query(FileTag)\
                            .filter_by(file_id=file_id).delete()

                    for label in raw_tags:
                        tag = self._session.query(Tag).filter_by(label=label).first()
                        if tag is None:
                            tag = Tag(label=label)
                            self._session.add(tag)
                            self._session.flush()
                        exists = self._session.query(FileTag)\
                            .filter_by(file_id=file_id, tag_id=tag.id).first()
                        if not exists:
                            self._session.add(FileTag(file_id=file_id, tag_id=tag.id))

                self._session.commit()

                # Write EXIF/IPTC for photos
                if rec.get("file_type") == "photo" and Path(rec["filepath"]).exists():
                    if do_title or do_subject:
                        self._write_title_subject_exif(
                            rec["filepath"], meta.title, meta.subject
                        )
                    if do_tags:
                        all_tags = [
                            r.label for r in
                            self._session.query(Tag.label)
                            .join(FileTag, FileTag.tag_id == Tag.id)
                            .filter(FileTag.file_id == file_id)
                            .order_by(Tag.label).all()
                        ]
                        write_tags_to_file(rec["filepath"], all_tags)

                # Attempt auto-rename now conditions may be met
                maybe_auto_rename(file_id, self._session)

                changed += 1
            except Exception as e:
                self._session.rollback()
                log.error(f"Bulk edit failed for {rec['filename']}: {e}")

        self._progress_lbl.setText(
            f"Done — {changed:,} photo{'s' if changed != 1 else ''} updated."
        )
        self._progress_lbl.setStyleSheet("color:#a6e3a1; font-size:11px;")
        self.changes_applied.emit()
        self._apply_btn.setEnabled(True)

    def _write_title_subject_exif(self, filepath: str,
                                   title: str | None, subject: str | None):
        import subprocess
        from memoria.exif_writer import _exiftool_path
        tool = _exiftool_path()
        if not tool:
            return
        args = [
            tool, "-overwrite_original", "-charset", "UTF8",
            f"-IPTC:ObjectName={title or ''}",
            f"-XMP-dc:Title={title or ''}",
            f"-IPTC:Caption-Abstract={subject or ''}",
            f"-XMP-dc:Description={subject or ''}",
            filepath,
        ]
        try:
            subprocess.run(args, capture_output=True, timeout=15)
        except Exception as e:
            log.warning(f"exiftool title/subject write failed for {filepath}: {e}")
