"""
Activity Log Panel
──────────────────
Collapsible panel shown below the photo grid.
Displays entries from the edit_log table.

• User edits:  shown as pending until written to EXIF.
• AI actions:  shown with ✓ / ✗ confirmation buttons.
              (Feedback is stored — useful for future tuning of thresholds.)
"""
from __future__ import annotations

import logging
from collections import defaultdict

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

log = logging.getLogger(__name__)


class LogPanel(QWidget):
    """
    Signals
    -------
    closed              — user clicked ✕; parent should hide the panel and
                          update the toolbar toggle button state
    exif_write_requested(filepath, title, subject)
                        — emitted for each file that needs an EXIF write;
                          parent (MainWindow) performs the actual write
    """
    closed = pyqtSignal()
    exif_write_requested  = pyqtSignal(str, str, str)   # filepath, title, subject
    tags_write_requested  = pyqtSignal(int, str)        # file_id, filepath

    _COLS = ("Time", "File", "Action", "Old", "New Value", "Source", "Confirm")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("logPanel")
        self.setStyleSheet(
            "QWidget#logPanel { background:#1a1a1a; border-top:1px solid #333; }"
        )
        self.setMinimumHeight(160)
        self.setMaximumHeight(240)

        self._filter_mode = "all"    # "all" | "pending" | "ai"
        self._rows_data: list[dict] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header bar ──────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(30)
        header.setStyleSheet("background:#252526; border-bottom:1px solid #333;")
        hrow = QHBoxLayout(header)
        hrow.setContentsMargins(8, 0, 8, 0)
        hrow.setSpacing(4)

        _filt_css = (
            "QPushButton { background:transparent; color:#888; border:none; "
            "font-size:11px; padding:2px 8px; border-radius:3px; }"
            "QPushButton:hover { color:#ccc; }"
            "QPushButton:checked { background:#37373d; color:#fff; }"
        )
        self._btn_all     = QPushButton("All")
        self._btn_pending = QPushButton("Pending")
        self._btn_ai      = QPushButton("AI Actions")
        for btn in (self._btn_all, self._btn_pending, self._btn_ai):
            btn.setCheckable(True)
            btn.setStyleSheet(_filt_css)
            btn.setFixedHeight(22)
            hrow.addWidget(btn)
        self._btn_all.setChecked(True)
        self._btn_all.clicked.connect(lambda: self._set_filter("all"))
        self._btn_pending.clicked.connect(lambda: self._set_filter("pending"))
        self._btn_ai.clicked.connect(lambda: self._set_filter("ai"))

        hrow.addStretch()

        self._confirm_all_btn = QPushButton("Confirm all AI ✓")
        self._confirm_all_btn.setFixedHeight(22)
        self._confirm_all_btn.setToolTip("Mark all unconfirmed AI actions as correct")
        self._confirm_all_btn.clicked.connect(self._confirm_all_ai)
        self._confirm_all_btn.hide()   # shown only when unconfirmed AI rows exist
        self._confirm_all_btn.setStyleSheet(
            "QPushButton { background:#2a4a2a; color:#a6e3a1; border:1px solid #3a6a3a; "
            "border-radius:3px; font-size:11px; padding:0 8px; }"
            "QPushButton:hover { background:#3a6a3a; }"
        )
        hrow.addWidget(self._confirm_all_btn)

        self._write_btn = QPushButton("Write pending to files")
        self._write_btn.setFixedHeight(22)
        self._write_btn.clicked.connect(self._write_pending)
        self._update_write_btn(has_pending=False)   # start grey; refreshed with data
        hrow.addWidget(self._write_btn)

        _hdr_lbl = QLabel("Activity Log")
        _hdr_lbl.setStyleSheet("color:#555; font-size:11px; padding:0 8px;")
        hrow.addWidget(_hdr_lbl)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#666; border:none; font-size:11px; }"
            "QPushButton:hover { color:#ccc; }"
        )
        close_btn.clicked.connect(self.closed.emit)
        hrow.addWidget(close_btn)

        outer.addWidget(header)

        # ── Table ───────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(len(self._COLS))
        self._table.setHorizontalHeaderLabels(self._COLS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().hide()
        self._table.setShowGrid(False)
        self._table.setColumnWidth(0, 72)    # Time
        self._table.setColumnWidth(1, 170)   # File
        self._table.setColumnWidth(2, 90)    # Action
        self._table.setColumnWidth(3, 120)   # Old
        self._table.setColumnWidth(5, 46)    # Source
        self._table.setColumnWidth(6, 76)    # Confirm
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)  # New Value stretches
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.setStyleSheet("""
            QTableWidget {
                background:#1e1e1e; border:none; font-size:11px; color:#d4d4d4;
                outline:none;
            }
            QTableWidget::item { padding:1px 6px; border:none; }
            QTableWidget::item:selected { background:#37373d; }
            QTableWidget::item:alternate { background:#222222; }
            QHeaderView::section {
                background:#252526; color:#666; border:none;
                border-bottom:1px solid #333; padding:3px 6px; font-size:10px;
            }
        """)
        outer.addWidget(self._table)

    # ── Public API ────────────────────────────────────────────────────────

    def has_pending(self) -> bool:
        """Return True if there are unsaved user edits waiting to be written."""
        return any(not r["saved"] and r["source"] == "user" for r in self._rows_data)

    def pending_count(self) -> int:
        """Number of unsaved user edit entries."""
        return sum(1 for r in self._rows_data if not r["saved"] and r["source"] == "user")

    def refresh(self, preserve_scroll: bool = False):
        """Reload all entries from the edit_log DB table and repopulate."""
        scroll_pos = self._table.verticalScrollBar().value() if preserve_scroll else 0
        self._rows_data = self._load_from_db()
        self._populate_table()
        if preserve_scroll and scroll_pos:
            self._table.verticalScrollBar().setValue(scroll_pos)

    # ── Internal ──────────────────────────────────────────────────────────

    def _load_from_db(self) -> list[dict]:
        try:
            from memoria.database.db import get_session
            from memoria.database.models import EditLog
            session = get_session()
            try:
                rows = (
                    session.query(EditLog)
                    .order_by(EditLog.timestamp.desc())
                    .limit(300)
                    .all()
                )
                return [
                    {
                        "id":           r.id,
                        "timestamp":    r.timestamp,
                        "file_id":      r.file_id,
                        "filename":     r.filename or "",
                        "filepath":     r.filepath or "",
                        "action_type":  r.action_type,
                        "old_value":    r.old_value or "",
                        "new_value":    r.new_value or "",
                        "source":       r.source or "user",
                        "saved":        bool(r.saved),
                        "ai_confirmed": r.ai_confirmed,
                    }
                    for r in rows
                ]
            finally:
                session.close()
        except Exception as e:
            log.warning(f"LogPanel DB load failed: {e}")
            return []

    def _update_write_btn(self, has_pending: bool):
        """Style the write button: accent colour when pending, grey otherwise."""
        from memoria.ui.theme import accent
        a = accent()
        if has_pending:
            self._write_btn.setEnabled(True)
            self._write_btn.setStyleSheet(
                f"QPushButton {{ background:{a}; color:#fff; border:1px solid {a}; "
                f"border-radius:3px; font-size:11px; padding:0 8px; font-weight:600; }}"
                f"QPushButton:hover {{ background:{a}dd; }}"
                f"QPushButton:pressed {{ background:{a}99; }}"
            )
        else:
            self._write_btn.setEnabled(False)
            self._write_btn.setStyleSheet(
                "QPushButton { background:#2a2a2a; color:#555; border:1px solid #3a3a3a; "
                "border-radius:3px; font-size:11px; padding:0 8px; }"
            )

    def _set_filter(self, mode: str):
        self._filter_mode = mode
        for btn, m in (
            (self._btn_all,     "all"),
            (self._btn_pending, "pending"),
            (self._btn_ai,      "ai"),
        ):
            btn.setChecked(m == mode)
        self._populate_table()

    def _populate_table(self):
        rows = self._rows_data

        if self._filter_mode == "pending":
            rows = [r for r in rows if not r["saved"]]
        elif self._filter_mode == "ai":
            rows = [r for r in rows if r["source"] == "ai"]

        has_pending = any(not r["saved"] and r["source"] == "user" for r in self._rows_data)
        self._update_write_btn(has_pending)

        unconfirmed_ai = any(
            r["source"] == "ai" and r["ai_confirmed"] is None
            for r in self._rows_data
        )
        self._confirm_all_btn.setVisible(unconfirmed_ai)

        self._table.setRowCount(0)
        for row_data in rows:
            row_idx = self._table.rowCount()
            self._table.insertRow(row_idx)
            self._table.setRowHeight(row_idx, 22)

            ts = row_data["timestamp"]
            time_str = ts.strftime("%H:%M:%S") if ts else ""

            fn = row_data["filename"]
            if len(fn) > 32:
                fn = "…" + fn[-30:]

            def _item(text: str, colour: str | None = None) -> QTableWidgetItem:
                it = QTableWidgetItem(text)
                if colour:
                    it.setForeground(QColor(colour))
                return it

            is_saved = row_data["saved"]
            dim = "#555" if is_saved else None

            self._table.setItem(row_idx, 0, _item(time_str,                  dim or "#666"))
            self._table.setItem(row_idx, 1, _item(fn,                         dim))
            self._table.setItem(row_idx, 2, _item(row_data["action_type"],    dim))
            self._table.setItem(row_idx, 3, _item(row_data["old_value"],      dim or "#888"))
            self._table.setItem(row_idx, 4, _item(row_data["new_value"],      dim))

            src = row_data["source"]
            src_colour = "#888" if src == "user" else ("#7eb8f0" if not dim else "#555")
            self._table.setItem(row_idx, 5, _item(src, src_colour))

            # Confirm column
            ai_conf = row_data["ai_confirmed"]
            if src == "ai" and ai_conf is None:
                self._table.setCellWidget(
                    row_idx, 6, self._make_confirm_widget(row_data["id"])
                )
            elif ai_conf is True:
                self._table.setItem(row_idx, 6, _item("✓ correct", "#a6e3a1"))
            elif ai_conf is False:
                self._table.setItem(row_idx, 6, _item("✗ wrong",   "#f38ba8"))
            else:
                self._table.setItem(row_idx, 6, _item(""))

    def _make_confirm_widget(self, log_id: int) -> QWidget:
        """✓ / ✗ button pair for an AI action row."""
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        row = QHBoxLayout(w)
        row.setContentsMargins(2, 1, 2, 1)
        row.setSpacing(2)
        yes_btn = QPushButton("✓")
        no_btn  = QPushButton("✗")
        _btn_css = (
            "QPushButton { border:1px solid #444; border-radius:3px; "
            "background:#2d2d2d; font-size:11px; padding:0; }"
            "QPushButton:hover { background:#3a3a3a; }"
        )
        for btn in (yes_btn, no_btn):
            btn.setFixedSize(24, 18)
            btn.setStyleSheet(_btn_css)
        yes_btn.setStyleSheet(_btn_css + " QPushButton { color:#a6e3a1; }")
        no_btn.setStyleSheet( _btn_css + " QPushButton { color:#f38ba8; }")
        yes_btn.clicked.connect(lambda: self._confirm_ai(log_id, True))
        no_btn.clicked.connect( lambda: self._confirm_ai(log_id, False))
        row.addWidget(yes_btn)
        row.addWidget(no_btn)
        return w

    def _confirm_all_ai(self):
        """Mark every unconfirmed AI entry as confirmed correct in one DB call."""
        try:
            from memoria.database.db import get_session
            from memoria.database.models import EditLog
            session = get_session()
            try:
                entries = (
                    session.query(EditLog)
                    .filter(EditLog.source == "ai",
                            EditLog.ai_confirmed.is_(None))
                    .all()
                )
                for entry in entries:
                    entry.ai_confirmed = True
                session.commit()
            finally:
                session.close()
        except Exception as e:
            log.warning(f"Confirm all AI failed: {e}")
        self.refresh()

    def _confirm_ai(self, log_id: int, confirmed: bool):
        """Persist AI feedback and refresh the table."""
        try:
            from memoria.database.db import get_session
            from memoria.database.models import EditLog
            session = get_session()
            try:
                entry = session.query(EditLog).get(log_id)
                if entry:
                    entry.ai_confirmed = confirmed
                    session.commit()
            finally:
                session.close()
        except Exception as e:
            log.warning(f"Could not save AI confirmation for entry {log_id}: {e}")
        self.refresh(preserve_scroll=True)

    def _write_pending(self):
        """
        Write all pending (unsaved, user-sourced) edits to EXIF.
        Groups by file_id so each file gets one write call.
        Marks affected EditLog rows as saved=True.
        """
        try:
            from memoria.database.db import get_session
            from memoria.database.models import EditLog, Metadata
            session = get_session()
            try:
                pending = (
                    session.query(EditLog)
                    .filter(EditLog.saved == False, EditLog.source == "user")  # noqa: E712
                    .all()
                )

                # Collect latest value per file per field
                by_file: dict[int, dict] = defaultdict(dict)
                entry_ids: list[int] = []
                for entry in pending:
                    if entry.file_id and entry.filepath:
                        by_file[entry.file_id]["filepath"] = entry.filepath
                        # title/subject: keep latest value; tag_add/remove: just mark present
                        if entry.action_type in ("title", "subject"):
                            by_file[entry.file_id][entry.action_type] = entry.new_value
                        else:
                            by_file[entry.file_id][entry.action_type] = True
                        entry_ids.append(entry.id)

                for file_id, fields in by_file.items():
                    filepath = fields["filepath"]
                    # Use DB for any field not in the pending set
                    meta = session.query(Metadata).filter_by(file_id=file_id).first()

                    # Write title/subject if changed
                    if "title" in fields or "subject" in fields:
                        title   = fields.get("title",   (meta.title   if meta else "") or "")
                        subject = fields.get("subject", (meta.subject if meta else "") or "")
                        self.exif_write_requested.emit(filepath, title, subject)

                    # Write tags if any tag_add/tag_remove pending for this file
                    if "tag_add" in fields or "tag_remove" in fields:
                        self.tags_write_requested.emit(file_id, filepath)

                # Mark written
                for eid in entry_ids:
                    e = session.query(EditLog).get(eid)
                    if e:
                        e.saved = True
                session.commit()
            finally:
                session.close()
        except Exception as e:
            log.warning(f"LogPanel write_pending failed: {e}")
        self.refresh()
