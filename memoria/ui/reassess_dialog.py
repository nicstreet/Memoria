"""
Reassess Dialog
───────────────
Runs the three-step re-assessment pipeline in a background thread:
  1. Scan any unprocessed photos for faces.
  2. Match unassigned detections against known-person galleries.
  3. Re-cluster whatever remains.

Shows live progress and a summary when done.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel,
    QProgressBar, QVBoxLayout,
)

log = logging.getLogger(__name__)


# ── Background worker ─────────────────────────────────────────────────────────

class _ReassessWorker(QObject):
    progress = pyqtSignal(int, int, str)   # current, total, message
    finished = pyqtSignal(dict)            # stats dict

    def __init__(self, session):
        super().__init__()
        self._session = session

    def run(self):
        try:
            from memoria.faces.clustering import run_reassess
            stats = run_reassess(self._session, progress=self._on_progress)
            self.finished.emit(stats)
        except Exception as e:
            log.error(f"Reassess failed: {e}", exc_info=True)
            self.finished.emit({"error": str(e)})

    def _on_progress(self, current: int, total: int, message: str):
        self.progress.emit(current, total, message)


# ── Dialog ────────────────────────────────────────────────────────────────────

class ReassessDialog(QDialog):
    """Shows progress while the reassess pipeline runs, then displays results."""

    reassess_complete = pyqtSignal()   # emitted when work finishes

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self._session = session
        self.setWindowTitle("Re-assess photos for faces & names")
        self.setMinimumWidth(420)
        self.setModal(True)
        self.setStyleSheet("""
            QDialog    { background: #1e1e1e; color: #d4d4d4; }
            QLabel     { color: #d4d4d4; }
            QProgressBar {
                background: #2a2a2a; border: 1px solid #444;
                border-radius: 4px; height: 14px; text-align: center;
                color: #d4d4d4;
            }
            QProgressBar::chunk { background: #7c6af7; border-radius: 3px; }
            QPushButton {
                background: #3a3a3a; color: #d4d4d4; border: 1px solid #555;
                border-radius: 4px; padding: 5px 14px;
            }
            QPushButton:hover    { background: #4a4a4a; }
            QPushButton:disabled { color: #555; border-color: #333; }
        """)
        self._build_ui()
        self._start()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        self._heading = QLabel(
            "<b>Scanning photos and matching faces to known people…</b>"
        )
        self._heading.setStyleSheet("font-size: 13px; color: #d4d4d4;")
        layout.addWidget(self._heading)

        self._step_lbl = QLabel("Starting…")
        self._step_lbl.setStyleSheet("color: #9a9a9a; font-size: 12px;")
        layout.addWidget(self._step_lbl)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)   # indeterminate initially
        layout.addWidget(self._bar)

        self._detail_lbl = QLabel("")
        self._detail_lbl.setStyleSheet("color: #777; font-size: 11px;")
        layout.addWidget(self._detail_lbl)

        self._btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self._btns.rejected.connect(self.reject)
        self._btns.button(QDialogButtonBox.StandardButton.Close).setEnabled(False)
        layout.addWidget(self._btns)

    # ── Worker wiring ─────────────────────────────────────────────────────────

    def _start(self):
        self._thread = QThread()
        self._worker = _ReassessWorker(self._session)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)

        self._thread.start()

    def _on_progress(self, current: int, total: int, message: str):
        if total > 0:
            self._bar.setRange(0, total)
            self._bar.setValue(current)
        self._detail_lbl.setText(message)

        # Map step header from the pipeline stages
        if "step 1" in message.lower() or "scanning" in message.lower():
            self._step_lbl.setText("Step 1 of 4 — scanning unprocessed photos for faces")
        elif "step 2" in message.lower() or "matching" in message.lower():
            self._step_lbl.setText("Step 2 of 4 — matching faces to known people")
        elif "step 3" in message.lower() or "clustering" in message.lower():
            self._step_lbl.setText("Step 3 of 4 — clustering remaining unassigned faces")
        elif "step 4" in message.lower() or "auditing" in message.lower():
            self._step_lbl.setText("Step 4 of 5 — auditing person-name tags")
        elif "step 5" in message.lower() or "syncing tags" in message.lower():
            self._step_lbl.setText("Step 5 of 5 — writing tags to file metadata (EXIF/IPTC)")
        elif "done" in message.lower():
            self._step_lbl.setText("Complete")

    def _on_finished(self, stats: dict):
        self._bar.setRange(0, 1)
        self._bar.setValue(1)

        if "error" in stats:
            self._heading.setText("<b>Re-assessment failed</b>")
            self._step_lbl.setText(stats["error"])
            self._step_lbl.setStyleSheet("color: #f38ba8; font-size: 12px;")
        else:
            self._heading.setText("<b>Re-assessment complete</b>")
            self._step_lbl.setText("Results:")

            lines = []
            if stats.get("scanned"):
                lines.append(f"• {stats['scanned']:,} photo(s) scanned for faces")
            if stats.get("faces_found"):
                lines.append(f"• {stats['faces_found']:,} new face(s) detected")
            if "matched" in stats:
                lines.append(f"• {stats['matched']:,} face(s) matched to known people")
            if stats.get("unmatched"):
                lines.append(f"• {stats['unmatched']:,} face(s) still unidentified "
                             f"(check log for distance diagnostics)")
            if "clusters" in stats:
                lines.append(f"• {stats['clusters']:,} new cluster(s) ready to name")
            if stats.get("tags_added"):
                lines.append(f"• {stats['tags_added']:,} missing person-name tag(s) applied")
            if stats.get("files_written"):
                lines.append(f"• {stats['files_written']:,} photo(s) updated with EXIF/IPTC tags")

            self._detail_lbl.setText("\n".join(lines) if lines else "Nothing new found.")
            self._detail_lbl.setStyleSheet("color: #a6e3a1; font-size: 12px; line-height: 1.6;")

        self._btns.button(QDialogButtonBox.StandardButton.Close).setEnabled(True)
        self.reassess_complete.emit()

    def closeEvent(self, event):
        # Don't allow closing while the thread is still running
        if self._thread.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)
