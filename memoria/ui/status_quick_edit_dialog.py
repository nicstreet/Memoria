"""
Status Quick-Edit Dialog
─────────────────────────
Opened by clicking the status overlay on a grid thumbnail.

Shows only the fields that appear in the active completion criteria,
pre-populated with their current values.  The user can edit them and
hit Apply (saves to DB + writes EXIF) without leaving the grid.

Buttons:
  Apply           — write all changes, close
  Mark Incomplete — adds the [incomplete] tag (written to EXIF),
                    dismisses red indicators for this photo
  Reset           — revert inputs to saved values
  Close           — discard edits
"""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QCompleter, QDialog, QDialogButtonBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)

from memoria.file_status import (
    FIELD_LABELS, INTENTIONALLY_INCOMPLETE_TAG, compute_status, get_criteria,
)

log = logging.getLogger(__name__)

_INPUT_CSS = """
    QLineEdit, QComboBox {
        background:#3a3a3a; border:1px solid #555; border-radius:4px;
        color:#d4d4d4; padding:3px 8px; font-size:12px;
    }
    QLineEdit:focus, QComboBox:focus { border-color:#7c6af7; }
    QComboBox::drop-down { border:none; width:20px; }
    QComboBox QAbstractItemView {
        background:#2d2d2d; color:#d4d4d4;
        selection-background-color:#5a4fd4; border:1px solid #555;
    }
"""
_LABEL_CSS  = "color:#aaa; font-size:12px; min-width:90px;"
_STATUS_OK  = "color:#a6e3a1; font-size:11px;"
_STATUS_ERR = "color:#f38ba8; font-size:11px;"
_STATUS_AMB = "color:#e6a817; font-size:11px;"


class StatusQuickEditDialog(QDialog):
    """Quick-edit dialog for completion-criteria fields."""

    changes_applied = pyqtSignal(int)   # emits file_id after apply

    def __init__(self, session, record: dict,
                 criteria: dict | None = None, parent=None):
        super().__init__(parent)
        self._session  = session
        self._record   = record
        self._criteria = criteria or get_criteria()
        self._file_id  = record["id"]

        self.setWindowTitle(f"Complete — {record['filename']}")
        self.setMinimumWidth(440)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.setStyleSheet(f"""
            QDialog   {{ background:#1e1e1e; color:#d4d4d4; }}
            QLabel    {{ color:#d4d4d4; font-size:12px; }}
            QPushButton {{
                background:#3a3a3a; color:#d4d4d4; border:1px solid #555;
                border-radius:4px; padding:4px 14px; font-size:12px;
            }}
            QPushButton:hover    {{ background:#4a4a4a; }}
            QPushButton:disabled {{ color:#555; border-color:#333; }}
            QPushButton#apply {{
                background:#7c6af7; border-color:#7c6af7; color:#fff;
            }}
            QPushButton#apply:hover {{ background:#9480ff; }}
            QPushButton#incomplete {{
                background:#5a3a10; border-color:#e6a817; color:#e6a817;
            }}
            QPushButton#incomplete:hover {{ background:#7a5020; }}
            {_INPUT_CSS}
        """)

        self._build_ui()
        self._load_values()

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # Filename heading
        fname = QLabel(self._record["filename"])
        fname.setStyleSheet("color:#888; font-size:11px;")
        root.addWidget(fname)

        # One row per active criterion
        self._inputs: dict[str, QWidget] = {}   # criterion_key → input widget
        self._row_status: dict[str, QLabel] = {}

        active_keys = [k for k in FIELD_LABELS if self._criteria.get(k, False)]
        for key in active_keys:
            self._add_field_row(root, key)

        # Status message
        self._msg_lbl = QLabel("")
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.setStyleSheet("color:#777; font-size:11px;")
        root.addWidget(self._msg_lbl)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._incomplete_btn = QPushButton("⚐  Mark Incomplete")
        self._incomplete_btn.setObjectName("incomplete")
        self._incomplete_btn.setToolTip(
            "Applies the [incomplete] tag to this photo — suppresses red indicators "
            "to show you've intentionally left these fields empty."
        )
        self._incomplete_btn.clicked.connect(self._mark_incomplete)
        btn_row.addWidget(self._incomplete_btn)

        btn_row.addStretch()

        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._load_values)
        btn_row.addWidget(reset_btn)

        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("apply")
        apply_btn.clicked.connect(self._apply)
        btn_row.addWidget(apply_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

    def _add_field_row(self, root: QVBoxLayout, key: str):
        """Add an appropriate input widget for this criterion key."""
        row = QWidget()
        row.setStyleSheet("background:transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        label = QLabel(f"{FIELD_LABELS[key]}:")
        label.setStyleSheet(_LABEL_CSS)
        h.addWidget(label)

        widget: QWidget | None = None

        if key == "require_title":
            w = QLineEdit()
            w.setPlaceholderText("Enter title…")
            widget = w

        elif key == "require_subject":
            from memoria.ui.default_subjects import ALL_SUBJECTS
            from PyQt6.QtWidgets import QMenu
            container = QWidget()
            container.setStyleSheet("background:transparent;")
            ch = QHBoxLayout(container)
            ch.setContentsMargins(0, 0, 0, 0)
            ch.setSpacing(4)
            w = QLineEdit()
            w.setPlaceholderText("Enter subject…")
            comp = QCompleter(ALL_SUBJECTS, w)
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
            w.setCompleter(comp)
            ch.addWidget(w, stretch=1)
            drop = QPushButton("▾")
            drop.setFixedSize(24, 24)
            drop.setStyleSheet(
                "QPushButton{background:#3a3a3a;border:1px solid #555;"
                "border-radius:4px;color:#aaa;padding:0;}"
                "QPushButton:hover{background:#4a4a4a;}"
            )
            def _show_subj_menu(btn=drop, edit=w):
                from memoria.ui.default_subjects import SUBJECT_CATEGORIES
                m = QMenu(self)
                m.setStyleSheet(
                    "QMenu{background:#252526;color:#d4d4d4;border:1px solid #444;}"
                    "QMenu::item{padding:4px 20px 4px 10px;font-size:11px;}"
                    "QMenu::item:selected{background:#5a4fd4;}"
                )
                for cat, subs in SUBJECT_CATEGORIES:
                    sub = m.addMenu(cat); sub.setStyleSheet(m.styleSheet())
                    for s in subs:
                        sub.addAction(s).triggered.connect(
                            lambda _, v=s, e=edit: e.setText(v)
                        )
                m.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
            drop.clicked.connect(_show_subj_menu)
            ch.addWidget(drop)
            widget = container
            # Store the inner line edit for value access
            self._inputs[key] = w
            h.addWidget(container, stretch=1)

        elif key == "require_location":
            w = QComboBox()
            w.setEditable(True)
            w.lineEdit().setPlaceholderText("Enter location…")
            try:
                self._session.expire_all()
                from memoria.database.models import Metadata as _M
                rows = (
                    self._session.query(_M.location_label)
                    .filter(_M.location_label.isnot(None), _M.location_label != "")
                    .distinct().order_by(_M.location_label).all()
                )
                w.addItem("")
                for r in rows:
                    w.addItem(r.location_label)
            except Exception:
                pass
            widget = w

        elif key == "require_tags":
            w = QTextEdit()
            min_t = self._criteria.get("min_tags", 1)
            w.setPlaceholderText(f"Tags, comma-separated (need ≥{min_t})")
            w.setAcceptRichText(False)
            w.setFixedHeight(64)
            w.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            w.setStyleSheet(
                "QTextEdit{background:#3a3a3a;border:1px solid #555;"
                "border-radius:4px;color:#d4d4d4;padding:4px 8px;font-size:12px;}"
                "QTextEdit:focus{border-color:#7c6af7;}"
            )
            widget = w

        elif key == "require_copyright":
            w = QLineEdit()
            w.setPlaceholderText("© 2024 Photographer Name")
            widget = w

        else:
            # Read-only info for faces, AI, filename, date
            w = QLabel("—")
            w.setStyleSheet("color:#666; font-size:11px;")
            widget = w

        if key not in self._inputs:
            self._inputs[key] = widget

        if widget and not h.count() > 2:   # subject combo already added
            h.addWidget(widget, stretch=1)

        # Status dot
        dot = QLabel("○")
        dot.setFixedSize(16, 16)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setStyleSheet("color:#555; font-size:11px;")
        h.addWidget(dot)
        self._row_status[key] = dot

        root.addWidget(row)

    # ── Data ────────────────────────────────────────────────────────────────

    def _load_values(self):
        """Populate inputs from the DB."""
        try:
            from memoria.database.models import FileTag, Metadata, Tag
            meta = (
                self._session.query(Metadata)
                .filter_by(file_id=self._file_id).first()
            )
            tags = [
                r.label for r in (
                    self._session.query(Tag.label)
                    .join(FileTag, FileTag.tag_id == Tag.id)
                    .filter(FileTag.file_id == self._file_id)
                    .order_by(Tag.label).all()
                )
                if r.label != INTENTIONALLY_INCOMPLETE_TAG
            ]
        except Exception as e:
            log.warning(f"StatusQuickEdit load failed: {e}")
            return

        def _set(key, val):
            w = self._inputs.get(key)
            if w is None:
                return
            if isinstance(w, QTextEdit):
                w.setPlainText(val or "")
            elif isinstance(w, QLineEdit):
                w.setText(val or "")
            elif isinstance(w, QComboBox):
                w.setCurrentText(val or "")
            elif isinstance(w, QLabel):
                w.setText(val or "—")

        _set("require_title",    meta.title    if meta else "")
        _set("require_subject",  meta.subject  if meta else "")
        _set("require_location", meta.location_label if meta else "")
        _set("require_tags",     ", ".join(tags))
        _set("require_copyright", meta.copyright if meta else "")

        # Read-only status fields
        st = compute_status(self._file_id, self._session, self._criteria)
        self._update_dots(st)

        self._update_incomplete_btn(st.get("intentional", False))

    def _update_dots(self, st: dict):
        fields = st.get("fields", {})
        intentional = st.get("intentional", False)
        for key, dot in self._row_status.items():
            ok = fields.get(key)
            if ok is None:
                dot.setText("—")
                dot.setStyleSheet("color:#555; font-size:11px;")
            elif intentional:
                dot.setText("◐")
                dot.setStyleSheet(_STATUS_AMB)
            elif ok:
                dot.setText("●")
                dot.setStyleSheet(_STATUS_OK)
            else:
                dot.setText("●")
                dot.setStyleSheet(_STATUS_ERR)

    def _update_incomplete_btn(self, is_intentional: bool):
        if is_intentional:
            self._incomplete_btn.setText("✓  Marked Incomplete")
            self._incomplete_btn.setStyleSheet(
                "QPushButton{background:#3a3a10;border:1px solid #888;"
                "color:#888;border-radius:4px;padding:4px 14px;font-size:12px;}"
                "QPushButton:hover{background:#4a4a20;}"
            )
        else:
            self._incomplete_btn.setText("⚐  Mark Incomplete")
            self._incomplete_btn.setObjectName("incomplete")
            self._incomplete_btn.setStyleSheet(
                "QPushButton#incomplete{background:#5a3a10;border-color:#e6a817;"
                "color:#e6a817;border-radius:4px;padding:4px 14px;font-size:12px;}"
                "QPushButton#incomplete:hover{background:#7a5020;}"
            )

    # ── Actions ─────────────────────────────────────────────────────────────

    def _apply(self):
        try:
            self._write_changes()
            self._msg_lbl.setText("✓  Saved.")
            self._msg_lbl.setStyleSheet(_STATUS_OK)
            st = compute_status(self._file_id, self._session, self._criteria)
            self._update_dots(st)
            self.changes_applied.emit(self._file_id)
        except Exception as e:
            self._msg_lbl.setText(f"Error: {e}")
            self._msg_lbl.setStyleSheet(_STATUS_ERR)
            log.error(f"StatusQuickEdit apply error: {e}", exc_info=True)

    def _write_changes(self):
        from memoria.database.models import FileTag, Metadata, Tag
        is_photo = self._record.get("file_type") == "photo"

        meta = self._session.query(Metadata).filter_by(
            file_id=self._file_id
        ).first()
        if meta is None:
            meta = Metadata(file_id=self._file_id)
            self._session.add(meta)

        dirty_ts   = False
        dirty_cr   = False
        dirty_tags = False

        def _val(key):
            w = self._inputs.get(key)
            if isinstance(w, QTextEdit):   return w.toPlainText().strip()
            if isinstance(w, QLineEdit):   return w.text().strip()
            if isinstance(w, QComboBox):   return w.currentText().strip()
            return ""

        if "require_title" in self._inputs:
            meta.title = _val("require_title") or None
            dirty_ts = True

        if "require_subject" in self._inputs:
            meta.subject = _val("require_subject") or None
            dirty_ts = True

        if "require_location" in self._inputs:
            meta.location_label = _val("require_location") or None

        if "require_copyright" in self._inputs:
            meta.copyright = _val("require_copyright") or None
            dirty_cr = True

        if "require_tags" in self._inputs:
            raw  = _val("require_tags")
            labels = [t.strip() for t in raw.split(",") if t.strip()
                      and t.strip() != INTENTIONALLY_INCOMPLETE_TAG]
            # Clear existing non-[incomplete] tags and re-add
            existing = (
                self._session.query(FileTag)
                .join(Tag, Tag.id == FileTag.tag_id)
                .filter(FileTag.file_id == self._file_id,
                        Tag.label != INTENTIONALLY_INCOMPLETE_TAG)
                .all()
            )
            for ft in existing:
                self._session.delete(ft)
            for label in labels:
                tag = self._session.query(Tag).filter_by(label=label).first()
                if not tag:
                    tag = Tag(label=label)
                    self._session.add(tag)
                    self._session.flush()
                self._session.add(FileTag(file_id=self._file_id, tag_id=tag.id))
            dirty_tags = True

        self._session.commit()

        # EXIF
        filepath = self._record.get("filepath", "")
        if is_photo and Path(filepath).exists():
            if dirty_ts and (meta.title is not None or meta.subject is not None):
                self._exif_title_subject(filepath, meta.title, meta.subject)
            if dirty_tags:
                from memoria.exif_writer import write_tags_to_file
                all_tags = [
                    r.label for r in (
                        self._session.query(Tag.label)
                        .join(FileTag, FileTag.tag_id == Tag.id)
                        .filter(FileTag.file_id == self._file_id)
                        .order_by(Tag.label).all()
                    )
                ]
                write_tags_to_file(filepath, all_tags)
            if dirty_cr and meta.copyright:
                self._exif_copyright(filepath, meta.copyright)

        # Auto-rename
        from memoria.file_status import maybe_auto_rename
        maybe_auto_rename(self._file_id, self._session)

    def _mark_incomplete(self):
        """Toggle the [incomplete] tag on this photo."""
        try:
            from memoria.database.models import FileTag, Tag
            tag = self._session.query(Tag).filter_by(
                label=INTENTIONALLY_INCOMPLETE_TAG
            ).first()
            if tag is None:
                tag = Tag(label=INTENTIONALLY_INCOMPLETE_TAG)
                self._session.add(tag)
                self._session.flush()

            existing = (
                self._session.query(FileTag)
                .filter_by(file_id=self._file_id, tag_id=tag.id).first()
            )
            if existing:
                # Toggle off
                self._session.delete(existing)
                self._session.commit()
                is_now = False
            else:
                # Toggle on
                self._session.add(
                    FileTag(file_id=self._file_id, tag_id=tag.id)
                )
                self._session.commit()
                # Write [incomplete] to EXIF tags
                filepath = self._record.get("filepath", "")
                if self._record.get("file_type") == "photo" and Path(filepath).exists():
                    from memoria.exif_writer import write_tags_to_file
                    all_tags = [
                        r.label for r in (
                            self._session.query(Tag.label)
                            .join(FileTag, FileTag.tag_id == Tag.id)
                            .filter(FileTag.file_id == self._file_id)
                            .order_by(Tag.label).all()
                        )
                    ]
                    write_tags_to_file(filepath, all_tags)
                is_now = True

            self._update_incomplete_btn(is_now)
            st = compute_status(self._file_id, self._session, self._criteria)
            self._update_dots(st)
            self.changes_applied.emit(self._file_id)

        except Exception as e:
            log.error(f"Mark incomplete failed: {e}", exc_info=True)

    # ── EXIF helpers ─────────────────────────────────────────────────────────

    def _exif_title_subject(self, filepath, title, subject):
        import subprocess
        from memoria.exif_writer import _exiftool_path
        tool = _exiftool_path()
        if not tool:
            return
        subprocess.run([
            tool, "-overwrite_original", "-charset", "UTF8",
            f"-IPTC:ObjectName={title or ''}",
            f"-XMP-dc:Title={title or ''}",
            f"-IPTC:Caption-Abstract={subject or ''}",
            f"-XMP-dc:Description={subject or ''}",
            filepath,
        ], capture_output=True, timeout=15)

    def _exif_copyright(self, filepath, copyright_):
        import subprocess
        from memoria.exif_writer import _exiftool_path
        tool = _exiftool_path()
        if not tool:
            return
        subprocess.run([
            tool, "-overwrite_original", "-charset", "UTF8",
            f"-EXIF:Copyright={copyright_}",
            f"-XMP-dc:Rights={copyright_}",
            filepath,
        ], capture_output=True, timeout=15)
