"""
Generate Metadata Dialog
────────────────────────
Batch-generates Title and Subject for photos using an AI vision API.

Workflow:
  1. Dialog opens with the current filtered/selected photos.
  2. User clicks Generate — a background worker sends each photo to the API
     one at a time and fills in the AI Title / AI Subject columns.
  3. User reviews and edits results inline before clicking Apply.
  4. Apply writes to the DB as pending activity-log entries (same path as
     manual edits — written to EXIF via Activity Log or auto_write_exif).
"""
from __future__ import annotations

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

log = logging.getLogger(__name__)

# Table column indices
_COL_CHECK   = 0
_COL_THUMB   = 1
_COL_FILE    = 2
_COL_TITLE   = 3   # AI-suggested, editable
_COL_SUBJECT = 4   # AI-suggested, editable
_COL_STATUS  = 5

_STATUS_PENDING    = "Pending"
_STATUS_PROCESSING = "Processing…"
_STATUS_DONE       = "Done"
_STATUS_SKIPPED    = "Skipped"
_STATUS_ERROR      = "Error"


# ── Background worker ─────────────────────────────────────────────────────────

class _GenerateWorker(QObject):
    """
    Processes one photo per step and emits a result/error signal.
    Runs in a QThread so the UI stays responsive.
    """
    row_done     = pyqtSignal(int, str, str)   # row_idx, title, subject
    row_error    = pyqtSignal(int, str)        # row_idx, error_message
    rate_limited = pyqtSignal(int)             # seconds remaining
    finished     = pyqtSignal()

    def __init__(self, rows: list[dict], api_key: str,
                 provider: str, model: str, batch_context: str = "",
                 locked_subject: str = ""):
        super().__init__()
        self._rows           = rows
        self._api_key        = api_key
        self._provider       = provider
        self._model          = model
        self._batch_context  = batch_context
        self._locked_subject = locked_subject
        self._cancel         = False

    def cancel(self):
        self._cancel = True

    def run(self):
        import time
        from memoria.ai.caption import generate_caption

        _RATE_LIMIT_RETRY = 15.0  # seconds to wait after a 429

        for row in self._rows:
            if self._cancel:
                break

            row_idx = row["row_idx"]
            try:
                result = generate_caption(
                    row["filepath"],
                    row["metadata"],
                    self._api_key,
                    self._provider,
                    self._model,
                    batch_context=self._batch_context,
                    locked_subject=self._locked_subject,
                )
                self.row_done.emit(row_idx, result["title"], result["subject"])
            except RuntimeError as exc:
                msg = str(exc)
                # On rate-limit (429), wait and retry once
                if "429" in msg:
                    log.warning(f"Rate limited on row {row_idx}, waiting {_RATE_LIMIT_RETRY}s…")
                    for i in range(int(_RATE_LIMIT_RETRY)):
                        if self._cancel:
                            break
                        self.rate_limited.emit(int(_RATE_LIMIT_RETRY) - i)
                        time.sleep(1.0)
                    if not self._cancel:
                        try:
                            result = generate_caption(
                                row["filepath"],
                                row["metadata"],
                                self._api_key,
                                self._provider,
                                self._model,
                                batch_context=self._batch_context,
                                locked_subject=self._locked_subject,
                            )
                            self.row_done.emit(row_idx, result["title"], result["subject"])
                            continue
                        except Exception as exc2:
                            msg = str(exc2)[:120]
                else:
                    msg = msg[:120]
                log.warning(f"Caption generation failed for row {row_idx}: {msg}")
                self.row_error.emit(row_idx, msg)
            except Exception as exc:
                short = str(exc)[:120]
                log.warning(f"Caption generation failed for row {row_idx}: {exc}")
                self.row_error.emit(row_idx, short)
        self.finished.emit()


# ── Dialog ────────────────────────────────────────────────────────────────────

class GenerateMetadataDialog(QDialog):
    """
    Batch AI metadata generation dialog.

    Parameters
    ----------
    records  : list of file record dicts from the main grid
    session  : SQLAlchemy session for reading metadata / people / tags
    parent   : parent widget
    """

    # Emitted after Apply so the grid / detail panel can refresh
    metadata_applied = pyqtSignal()

    def __init__(self, records: list[dict], session, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Metadata")
        self.resize(920, 580)
        self.setMinimumSize(700, 440)

        from memoria.ui.settings_store import load as _load
        from memoria.database.db import get_app_setting
        self._settings  = _load()
        self._session   = session
        self._api_key   = get_app_setting("ai_api_key", "")
        self._provider  = self._settings.get("ai_provider", "gemini")
        self._model     = self._settings.get("ai_caption_model", "gemini-1.5-flash")

        self._records   = [r for r in records if r.get("file_type") == "photo"]
        self._thread: QThread | None = None
        self._worker: _GenerateWorker | None = None
        self._running = False

        from memoria.ui.styles import get_dark_style
        self.setStyleSheet(get_dark_style())

        self._build_ui()
        self._populate_table()
        self._table.itemChanged.connect(self._on_item_changed)
        self._refresh_info_label()
        self._auto_detect_batch_context()

        if not self._api_key:
            self._show_no_key_banner()

    # ── UI construction ───────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # ── Info bar ──────────────────────────────────────────────────
        info_row = QHBoxLayout()
        self._info_lbl = QLabel()
        self._info_lbl.setStyleSheet("color:#999; font-size:12px;")
        info_row.addWidget(self._info_lbl)
        info_row.addStretch()

        self._no_key_lbl = QLabel(
            "⚠  No API key set — open <b>Options → AI</b> to add one"
        )
        self._no_key_lbl.setStyleSheet("color:#f9a825; font-size:12px;")
        self._no_key_lbl.hide()
        info_row.addWidget(self._no_key_lbl)

        root.addLayout(info_row)

        # ── Batch context row ──────────────────────────────────────────
        ctx_row = QHBoxLayout()
        ctx_row.setSpacing(6)
        ctx_lbl = QLabel("Event context:")
        ctx_lbl.setStyleSheet("color:#888; font-size:12px;")
        ctx_lbl.setFixedWidth(96)
        ctx_row.addWidget(ctx_lbl)

        self._batch_ctx_input = QLineEdit()
        self._batch_ctx_input.setPlaceholderText(
            "e.g. Paris Trip 2024  (auto-detected from photo metadata, edit if needed)"
        )
        self._batch_ctx_input.setStyleSheet("""
            QLineEdit {
                background:#2a2a2a; border:1px solid #444;
                border-radius:4px; color:#d4d4d4; padding:3px 8px; font-size:12px;
            }
            QLineEdit:focus { border-color:#7c6af7; }
        """)
        ctx_row.addWidget(self._batch_ctx_input, stretch=1)

        ctx_hint = QLabel("ⓘ")
        ctx_hint.setStyleSheet("color:#555; font-size:13px;")
        ctx_hint.setToolTip(
            "This shared context is sent with every photo so the AI produces\n"
            "consistent titles. Leave blank to caption each photo independently."
        )
        ctx_row.addWidget(ctx_hint)
        root.addLayout(ctx_row)

        # ── Subject row ────────────────────────────────────────────────
        subj_row = QHBoxLayout()
        subj_row.setSpacing(6)
        subj_lbl = QLabel("Subject:")
        subj_lbl.setStyleSheet("color:#888; font-size:12px;")
        subj_lbl.setFixedWidth(96)
        subj_row.addWidget(subj_lbl)

        self._subject_combo = QComboBox()
        self._subject_combo.setStyleSheet("""
            QComboBox {
                background:#2a2a2a; border:1px solid #444;
                border-radius:4px; color:#d4d4d4; padding:2px 8px; font-size:12px;
            }
            QComboBox:focus { border-color:#7c6af7; }
            QComboBox::drop-down {
                subcontrol-origin:padding; subcontrol-position:top right;
                width:20px; border-left:1px solid #444;
            }
            QComboBox QAbstractItemView {
                background:#2d2d2d; color:#d4d4d4;
                selection-background-color:#5a4fd4; border:1px solid #555;
            }
        """)
        self._subject_combo.addItem("Auto (AI) — decide per photo", "")
        self._subject_combo.insertSeparator(1)
        from memoria.ui.default_subjects import SUBJECT_CATEGORIES
        for category, subjects in SUBJECT_CATEGORIES:
            for subject in subjects:
                self._subject_combo.addItem(subject, subject)
        subj_row.addWidget(self._subject_combo, stretch=1)

        self._detect_subj_btn = QPushButton("Auto-detect")
        self._detect_subj_btn.setFixedWidth(90)
        self._detect_subj_btn.setToolTip(
            "Send a few sample photos to the AI to determine the best subject\n"
            "for the whole batch (uses one API call)"
        )
        self._detect_subj_btn.setStyleSheet(
            "QPushButton { background:#3a3a3a; color:#aaa; border:1px solid #555; "
            "border-radius:4px; padding:3px 8px; font-size:11px; }"
            "QPushButton:hover { background:#4a4a4a; color:#fff; }"
            "QPushButton:disabled { color:#555; border-color:#333; }"
        )
        self._detect_subj_btn.setEnabled(bool(self._api_key))
        self._detect_subj_btn.clicked.connect(self._run_subject_detection)
        subj_row.addWidget(self._detect_subj_btn)

        subj_hint = QLabel("ⓘ")
        subj_hint.setStyleSheet("color:#555; font-size:13px;")
        subj_hint.setToolTip(
            "Lock one subject for all photos in the batch.\n"
            "The AI will only generate titles — keeping subjects consistent.\n"
            "Use Auto-detect to let the AI suggest one based on sample photos."
        )
        subj_row.addWidget(subj_hint)
        root.addLayout(subj_row)

        # ── Table ─────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ["", "Photo", "Filename", "AI Title", "AI Subject", "Status"]
        )
        self._table.verticalHeader().hide()
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.SelectedClicked
        )
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 28)
        self._table.setColumnWidth(1, 52)
        self._table.setColumnWidth(2, 180)
        self._table.setColumnWidth(4, 140)
        self._table.setColumnWidth(5, 90)
        self._table.verticalHeader().setDefaultSectionSize(44)
        self._table.setStyleSheet("""
            QTableWidget {
                background:#1e1e1e; border:none; font-size:12px; color:#d4d4d4;
                outline:none;
            }
            QTableWidget::item { padding:2px 6px; border:none; }
            QTableWidget::item:selected { background:#37373d; }
            QTableWidget::item:alternate { background:#222222; }
            QTableWidget::item[editable="true"] { border-bottom:1px solid #555; }
            QHeaderView::section {
                background:#252526; color:#888; border:none;
                border-bottom:1px solid #333; padding:4px 6px; font-size:11px;
            }
        """)
        root.addWidget(self._table, stretch=1)

        # ── Progress bar ──────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, max(1, len(self._records)))
        self._progress.setValue(0)
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet("""
            QProgressBar { background:#2a2a2a; border:none; border-radius:3px; }
            QProgressBar::chunk { background:#7c6af7; border-radius:3px; }
        """)
        self._progress.hide()
        root.addWidget(self._progress)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color:#777; font-size:11px;")
        self._status_lbl.hide()
        root.addWidget(self._status_lbl)

        # ── Button row ────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        _btn_css = (
            "QPushButton { background:#3a3a3a; color:#d4d4d4; border:1px solid #555; "
            "border-radius:4px; padding:4px 16px; font-size:12px; }"
            "QPushButton:hover { background:#4a4a4a; }"
            "QPushButton:disabled { color:#555; border-color:#333; }"
        )

        self._sel_all_btn = QPushButton("Select All")
        self._sel_all_btn.setStyleSheet(_btn_css)
        self._sel_all_btn.clicked.connect(self._select_all)
        btn_row.addWidget(self._sel_all_btn)

        self._sel_none_btn = QPushButton("Select None")
        self._sel_none_btn.setStyleSheet(_btn_css)
        self._sel_none_btn.clicked.connect(self._select_none)
        btn_row.addWidget(self._sel_none_btn)

        btn_row.addStretch()

        self._generate_btn = QPushButton("Generate")
        self._generate_btn.setStyleSheet(
            "QPushButton { background:#7c6af7; color:#fff; border:1px solid #7c6af7; "
            "border-radius:4px; padding:4px 20px; font-size:12px; font-weight:600; }"
            "QPushButton:hover { background:#9480ff; }"
            "QPushButton:disabled { background:#3a3a3a; color:#555; border-color:#333; }"
        )
        self._generate_btn.setEnabled(bool(self._api_key))
        self._generate_btn.clicked.connect(self._start_generate)
        btn_row.addWidget(self._generate_btn)

        self._cancel_btn = QPushButton("Cancel generation")
        self._cancel_btn.setStyleSheet(_btn_css)
        self._cancel_btn.hide()
        self._cancel_btn.clicked.connect(self._cancel_generate)
        btn_row.addWidget(self._cancel_btn)

        self._apply_btn = QPushButton("Apply to selected")
        self._apply_btn.setStyleSheet(
            "QPushButton { background:#3a3a3a; color:#888; border:1px solid #333; "
            "border-radius:4px; padding:4px 16px; font-size:12px; }"
            "QPushButton:enabled { background:#7c6af7; color:#fff; border-color:#7c6af7; }"
            "QPushButton:enabled:hover { background:#9480ff; }"
            "QPushButton:disabled { color:#555; }"
        )
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._apply)
        btn_row.addWidget(self._apply_btn)

        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(_btn_css)
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        root.addLayout(btn_row)

    def _refresh_info_label(self):
        n_sel   = len(self._checked_rows())
        n_total = len(self._records)
        self._info_lbl.setText(
            f"<b>{n_sel}</b> of <b>{n_total}</b> photo{'s' if n_total != 1 else ''} selected "
            f"&nbsp;·&nbsp; Model: <b>{self._model}</b>"
        )

    def _auto_detect_batch_context(self):
        """
        Analyse the selected records' metadata and suggest a batch event context.

        Strategy:
        - Find the most common location_label (if ≥40% of records share it, use it)
        - Find the date range (min/max date_taken across all records)
        - Combine into a human-readable string like "Paris, France · Mar 2024"
        - Detect sub-groups separated by >12h gaps and note if there are multiple
        """
        from collections import Counter
        from datetime import datetime, timedelta

        payloads = self._build_row_payloads(list(range(len(self._records))))

        locations: list[str] = []
        dates: list[datetime] = []

        for p in payloads:
            m = p.get("metadata", {})
            if m.get("location_label"):
                locations.append(m["location_label"])
            if m.get("date_taken") and isinstance(m["date_taken"], datetime):
                dates.append(m["date_taken"])

        parts: list[str] = []

        # Dominant location
        if locations:
            most_common, count = Counter(locations).most_common(1)[0]
            if count / len(self._records) >= 0.4:
                parts.append(most_common)

        # Date range
        if dates:
            dates.sort()
            lo, hi = dates[0], dates[-1]
            if lo.date() == hi.date():
                parts.append(lo.strftime("%d %b %Y"))
            elif lo.year == hi.year and lo.month == hi.month:
                parts.append(f"{lo.strftime('%d')}–{hi.strftime('%d %b %Y')}")
            elif lo.year == hi.year:
                parts.append(f"{lo.strftime('%b')}–{hi.strftime('%b %Y')}")
            else:
                parts.append(f"{lo.strftime('%b %Y')}–{hi.strftime('%b %Y')}")

            # Warn if there are multiple distinct day-clusters (possible mixed events)
            day_gaps = [
                (dates[i+1] - dates[i]).total_seconds() / 3600
                for i in range(len(dates)-1)
            ]
            big_gaps = sum(1 for g in day_gaps if g > 12)
            if big_gaps >= 2:
                parts.append(f"({big_gaps + 1} separate days detected)")

        suggestion = " · ".join(parts)
        if suggestion:
            self._batch_ctx_input.setText(suggestion)

    def _run_subject_detection(self):
        """One-shot API call to detect the best subject for the batch."""
        from memoria.ai.caption import detect_batch_subject
        self._detect_subj_btn.setEnabled(False)
        self._detect_subj_btn.setText("Detecting…")
        checked = self._checked_rows()
        filepaths = [self._records[i]["filepath"] for i in (checked or range(len(self._records)))]
        batch_context = self._batch_ctx_input.text().strip()
        try:
            subject = detect_batch_subject(
                filepaths,
                self._api_key,
                self._model,
                batch_context=batch_context,
            )
            if subject:
                # Find and select the matching item in the combo
                idx = self._subject_combo.findData(subject)
                if idx < 0:
                    # Not in list — add it temporarily
                    self._subject_combo.addItem(subject, subject)
                    idx = self._subject_combo.count() - 1
                self._subject_combo.setCurrentIndex(idx)
        except Exception as exc:
            QMessageBox.warning(self, "Detection failed", str(exc))
        finally:
            self._detect_subj_btn.setEnabled(True)
            self._detect_subj_btn.setText("Auto-detect")

    def _show_no_key_banner(self):
        self._no_key_lbl.show()
        self._generate_btn.setEnabled(False)

    # ── Table population ──────────────────────────────────────────────────

    def _populate_table(self):
        self._table.setRowCount(0)
        for rec in self._records:
            row = self._table.rowCount()
            self._table.insertRow(row)

            # Checkbox
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked)
            self._table.setItem(row, _COL_CHECK, chk)

            # Thumbnail
            self._set_thumbnail(row, rec["filepath"])

            # Filename
            fn_item = QTableWidgetItem(rec["filename"])
            fn_item.setFlags(fn_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            fn_item.setForeground(QColor("#aaa"))
            self._table.setItem(row, _COL_FILE, fn_item)

            # AI Title (blank until generated)
            title_item = QTableWidgetItem("")
            title_item.setForeground(QColor("#888"))
            self._table.setItem(row, _COL_TITLE, title_item)

            # AI Subject
            subj_item = QTableWidgetItem("")
            subj_item.setForeground(QColor("#888"))
            self._table.setItem(row, _COL_SUBJECT, subj_item)

            # Status
            status_item = QTableWidgetItem(_STATUS_PENDING)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setForeground(QColor("#555"))
            self._table.setItem(row, _COL_STATUS, status_item)

    def _set_thumbnail(self, row: int, filepath: str):
        """Load a small thumbnail into the Photo column."""
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFixedSize(50, 42)
        try:
            from PIL import Image
            from io import BytesIO
            with Image.open(filepath) as img:
                img.thumbnail((50, 42))
                buf = BytesIO()
                img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            lbl.setPixmap(px)
        except Exception:
            lbl.setText("🖼")
            lbl.setStyleSheet("font-size:18px; color:#555;")
        self._table.setCellWidget(row, _COL_THUMB, lbl)

    # ── Selection helpers ─────────────────────────────────────────────────

    def _on_item_changed(self, item):
        if item.column() == _COL_CHECK:
            self._refresh_info_label()

    def _select_all(self):
        self._table.itemChanged.disconnect(self._on_item_changed)
        for r in range(self._table.rowCount()):
            self._table.item(r, _COL_CHECK).setCheckState(Qt.CheckState.Checked)
        self._table.itemChanged.connect(self._on_item_changed)
        self._refresh_info_label()

    def _select_none(self):
        self._table.itemChanged.disconnect(self._on_item_changed)
        for r in range(self._table.rowCount()):
            self._table.item(r, _COL_CHECK).setCheckState(Qt.CheckState.Unchecked)
        self._table.itemChanged.connect(self._on_item_changed)
        self._refresh_info_label()

    def _checked_rows(self) -> list[int]:
        return [
            r for r in range(self._table.rowCount())
            if self._table.item(r, _COL_CHECK).checkState() == Qt.CheckState.Checked
        ]

    # ── Generate ─────────────────────────────────────────────────────────

    def _build_row_payloads(self, row_indices: list[int]) -> list[dict]:
        """Build the list of {filepath, metadata} dicts the worker needs."""
        from memoria.database.models import Metadata, FilePeople, Person, FileTag, Tag
        payloads = []
        for i in row_indices:
            rec = self._records[i]
            meta: dict = {}
            try:
                m = self._session.query(Metadata).filter_by(file_id=rec["id"]).first()
                if m:
                    meta["location_label"] = m.location_label
                    meta["gps_lat"]        = m.gps_lat
                    meta["gps_lon"]        = m.gps_lon
                    meta["date_taken"]     = m.date_taken

                people = (
                    self._session.query(Person.name)
                    .join(FilePeople, FilePeople.person_id == Person.id)
                    .filter(FilePeople.file_id == rec["id"])
                    .all()
                )
                meta["people"] = [p.name for p in people]

                tags = (
                    self._session.query(Tag.label)
                    .join(FileTag, FileTag.tag_id == Tag.id)
                    .filter(FileTag.file_id == rec["id"])
                    .all()
                )
                meta["tags"] = [t.label for t in tags]
            except Exception as e:
                log.warning(f"Metadata load failed for row {i}: {e}")

            payloads.append({
                "row_idx":  i,
                "filepath": rec["filepath"],
                "metadata": meta,
            })
        return payloads

    def _start_generate(self):
        checked = self._checked_rows()
        if not checked:
            QMessageBox.information(self, "Nothing selected",
                                    "Tick at least one photo to generate metadata for.")
            return

        # Reset previously generated rows back to Pending
        for i in checked:
            self._set_row_status(i, _STATUS_PENDING)
            self._table.item(i, _COL_TITLE).setText("")
            self._table.item(i, _COL_SUBJECT).setText("")

        payloads = self._build_row_payloads(checked)

        self._running = True
        self._generate_btn.hide()
        self._cancel_btn.show()
        self._apply_btn.setEnabled(False)
        self._progress.setMaximum(len(payloads))
        self._progress.setValue(0)
        self._progress.show()
        self._status_lbl.setText(f"Processing 0 of {len(payloads)}…")
        self._status_lbl.show()

        self._done_count = 0
        self._total = len(payloads)

        batch_context  = self._batch_ctx_input.text().strip()
        locked_subject = self._subject_combo.currentData() or ""
        self._worker = _GenerateWorker(
            payloads, self._api_key, self._provider, self._model,
            batch_context=batch_context,
            locked_subject=locked_subject,
        )
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.row_done.connect(self._on_row_done)
        self._worker.row_error.connect(self._on_row_error)
        self._worker.rate_limited.connect(self._on_rate_limited)
        self._worker.finished.connect(self._on_generate_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

        # Mark all rows as "processing" while thread spins up
        for i in checked:
            self._set_row_status(i, _STATUS_PENDING)

    def _cancel_generate(self):
        if self._worker:
            self._worker.cancel()
        self._cancel_btn.setEnabled(False)
        self._status_lbl.setText("Cancelling…")

    def _on_row_done(self, row_idx: int, title: str, subject: str):
        """Called (in the GUI thread via queued signal) when one photo is done."""

        title_item = self._table.item(row_idx, _COL_TITLE)
        subj_item  = self._table.item(row_idx, _COL_SUBJECT)
        title_item.setText(title)
        title_item.setForeground(QColor("#d4d4d4"))
        subj_item.setText(subject)
        subj_item.setForeground(QColor("#d4d4d4"))
        self._set_row_status(row_idx, _STATUS_DONE)

        self._done_count += 1
        self._progress.setValue(self._done_count)
        self._status_lbl.setText(
            f"Processing {self._done_count} of {self._total}…"
        )

    def _on_rate_limited(self, secs_remaining: int):
        self._status_lbl.setText(
            f"⏳ Rate limit reached — retrying in {secs_remaining}s…"
        )

    def _on_row_error(self, row_idx: int, message: str):
        self._set_row_status(row_idx, _STATUS_ERROR, tooltip=message)
        self._done_count += 1
        self._progress.setValue(self._done_count)

    def _on_generate_finished(self):
        self._running = False
        done_count = sum(
            1 for r in range(self._table.rowCount())
            if (self._table.item(r, _COL_STATUS) or QTableWidgetItem()).text()
            == _STATUS_DONE
        )
        self._status_lbl.setText(
            f"Complete — {done_count} result{'s' if done_count != 1 else ''} ready to review"
        )
        self._apply_btn.setEnabled(done_count > 0)

    def _on_thread_finished(self):
        self._thread = None
        self._worker = None
        self._cancel_btn.hide()
        self._generate_btn.show()
        self._generate_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)   # reset for next run

    # ── Apply ────────────────────────────────────────────────────────────

    def _apply(self):
        """Write AI-generated titles and subjects to the DB as pending edits."""
        from memoria.database.db import get_session
        from memoria.database.models import Metadata, EditLog, File

        applied = 0
        session = get_session()
        try:
            for row in range(self._table.rowCount()):
                if self._table.item(row, _COL_CHECK).checkState() != Qt.CheckState.Checked:
                    continue
                status = self._table.item(row, _COL_STATUS).text()
                if status != _STATUS_DONE:
                    continue

                ai_title   = self._table.item(row, _COL_TITLE).text().strip()
                ai_subject = self._table.item(row, _COL_SUBJECT).text().strip()
                if not ai_title and not ai_subject:
                    continue

                rec      = self._records[row]
                file_id  = rec["id"]
                file_row = session.query(File).get(file_id)
                meta     = session.query(Metadata).filter_by(file_id=file_id).first()
                if meta is None:
                    meta = Metadata(file_id=file_id)
                    session.add(meta)
                    session.flush()

                for field, new_val in (("title", ai_title), ("subject", ai_subject)):
                    if not new_val:
                        continue
                    old_val = getattr(meta, field, None) or ""
                    setattr(meta, field, new_val)
                    session.add(EditLog(
                        file_id=file_id,
                        filename=rec["filename"],
                        filepath=rec["filepath"],
                        action_type=field,
                        old_value=old_val or None,
                        new_value=new_val,
                        source="ai",
                        saved=False,
                        ai_confirmed=None,
                    ))

                applied += 1

            session.commit()
        except Exception as exc:
            session.rollback()
            log.error(f"Apply failed: {exc}", exc_info=True)
            QMessageBox.warning(self, "Apply failed", str(exc))
            return
        finally:
            session.close()

        self.metadata_applied.emit()
        QMessageBox.information(
            self, "Applied",
            f"Metadata applied to {applied} photo{'s' if applied != 1 else ''}.\n\n"
            "Changes are saved in the database. Open the Activity Log to "
            "write them to the files.",
        )

    # ── Row status helper ─────────────────────────────────────────────────

    def _set_row_status(self, row: int, status: str, tooltip: str = ""):
        item = self._table.item(row, _COL_STATUS)
        if item is None:
            return
        item.setText(status)
        colour = {
            _STATUS_PENDING:    "#555",
            _STATUS_PROCESSING: "#7c6af7",
            _STATUS_DONE:       "#a6e3a1",
            _STATUS_SKIPPED:    "#888",
            _STATUS_ERROR:      "#f38ba8",
        }.get(status, "#888")
        item.setForeground(QColor(colour))
        if tooltip:
            item.setToolTip(tooltip)

    def closeEvent(self, event):
        if self._running and self._worker:
            self._worker.cancel()
        super().closeEvent(event)
