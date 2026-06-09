"""
Bulk Edit Dialog
────────────────
Apply metadata changes to all currently-displayed / selected photos.

Sections (each independently enabled via checkbox):
  • Title          — set or clear
  • Subject        — set from list or clear
  • Location       — set from history or clear
  • Tags — Add     — append tags to all
  • Tags — Remove  — remove specific tags from all
  • People         — assign a named person to all
  • Date / Time    — shift by ±N hours/minutes, or set a specific date
  • Copyright      — set Artist and/or Copyright EXIF fields
  • Filename       — template-based rename with live preview
  • Rating         — placeholder (future)
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateTimeEdit,
    QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QProgressBar, QPushButton, QRadioButton,
    QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

log = logging.getLogger(__name__)

# ── Shared styles ─────────────────────────────────────────────────────────────

_INPUT_CSS = """
    QLineEdit, QComboBox, QSpinBox, QDateTimeEdit {
        background:#3a3a3a; border:1px solid #555; border-radius:4px;
        color:#d4d4d4; padding:3px 8px; font-size:12px;
    }
    QLineEdit:focus, QComboBox:focus,
    QSpinBox:focus, QDateTimeEdit:focus { border-color:#7c6af7; }
    QLineEdit:disabled, QComboBox:disabled,
    QSpinBox:disabled, QDateTimeEdit:disabled { color:#555; background:#2a2a2a; }
    QComboBox::drop-down { border:none; width:20px; }
    QComboBox QAbstractItemView {
        background:#2d2d2d; color:#d4d4d4;
        selection-background-color:#5a4fd4; border:1px solid #555;
    }
    QSpinBox::up-button, QSpinBox::down-button { width:16px; }
    QDateTimeEdit::up-button, QDateTimeEdit::down-button { width:16px; }
"""

_SECTION_HDR_CSS = (
    "QWidget { background:#252526; border-radius:4px; }"
)
_SECTION_LBL_CSS = "color:#ccc; font-size:12px; font-weight:600;"
_HINT_CSS        = "color:#666; font-size:10px; padding-left:26px;"


# ── Section widget ────────────────────────────────────────────────────────────

class _Section(QWidget):
    """
    Collapsible form section with an enable-checkbox in the header.
    Body widgets are enabled/disabled when the checkbox toggles.
    """
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # Header
        hdr = QWidget()
        hdr.setStyleSheet(_SECTION_HDR_CSS)
        hdr.setFixedHeight(28)
        hrow = QHBoxLayout(hdr)
        hrow.setContentsMargins(8, 0, 8, 0)
        hrow.setSpacing(8)

        self._chk = QCheckBox()
        self._chk.setFixedSize(16, 16)
        self._chk.setStyleSheet("""
            QCheckBox::indicator {
                width:14px; height:14px; border-radius:3px;
                border:1px solid #555; background:#2a2a2a;
            }
            QCheckBox::indicator:checked {
                background:#7c6af7; border-color:#7c6af7;
            }
        """)
        hrow.addWidget(self._chk)

        lbl = QLabel(title)
        lbl.setStyleSheet(_SECTION_LBL_CSS)
        hrow.addWidget(lbl, stretch=1)
        outer.addWidget(hdr)

        # Body
        self._body = QWidget()
        self._body.setStyleSheet("background:transparent;")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(26, 0, 0, 0)
        self._body_layout.setSpacing(6)
        outer.addWidget(self._body)

        self._chk.stateChanged.connect(self._on_toggle)
        self._on_toggle(0)

    def _on_toggle(self, state):
        self._body.setEnabled(bool(state))

    def body(self) -> QVBoxLayout:
        return self._body_layout

    @property
    def active(self) -> bool:
        return self._chk.isChecked()

    def add(self, w: QWidget) -> QWidget:
        self._body_layout.addWidget(w)
        return w

    def add_row(self, label: str, widget: QWidget,
                hint: str = "") -> QWidget:
        row = QWidget()
        row.setStyleSheet("background:transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        lbl = QLabel(f"{label}:")
        lbl.setFixedWidth(88)
        lbl.setStyleSheet("color:#aaa; font-size:12px;")
        h.addWidget(lbl)
        h.addWidget(widget, stretch=1)
        self._body_layout.addWidget(row)
        if hint:
            hl = QLabel(hint)
            hl.setStyleSheet(_HINT_CSS)
            hl.setWordWrap(True)
            self._body_layout.addWidget(hl)
        return row


# ── Rename template engine ────────────────────────────────────────────────────

_RENAME_TOKENS = [
    ("{date}",     "Date taken  (YYYY-MM-DD)"),
    ("{year}",     "Year  (YYYY)"),
    ("{month}",    "Month  (MM)"),
    ("{day}",      "Day  (DD)"),
    ("{time}",     "Time taken  (HH-MM)"),
    ("{subject}",  "Subject"),
    ("{title}",    "Title"),
    ("{original}", "Original filename stem"),
    ("{seq}",      "Sequence number  (001, 002…)"),
]


def _apply_rename_template(
    template: str,
    record: dict,
    meta: dict | None,
    seq: int,
) -> str:
    """Return the new stem (no extension) for one file."""
    date_taken = (meta or {}).get("date_taken") or record.get("date_taken")
    stem       = Path(record["filepath"]).stem

    replacements = {
        "{date}":     date_taken.strftime("%Y-%m-%d") if date_taken else "unknown-date",
        "{year}":     date_taken.strftime("%Y")       if date_taken else "0000",
        "{month}":    date_taken.strftime("%m")       if date_taken else "00",
        "{day}":      date_taken.strftime("%d")       if date_taken else "00",
        "{time}":     date_taken.strftime("%H-%M")    if date_taken else "00-00",
        "{subject}":  ((meta or {}).get("subject") or "").strip() or "unknown",
        "{title}":    ((meta or {}).get("title")   or "").strip() or stem,
        "{original}": stem,
        "{seq}":      f"{seq:03d}",
    }
    result = template
    for token, value in replacements.items():
        # Sanitise value for use in a filename
        value = re.sub(r'[<>:"/\\|?*]', "_", value)
        result = result.replace(token, value)
    return result.strip()


# ── Main dialog ───────────────────────────────────────────────────────────────

class BulkEditDialog(QDialog):
    """Apply metadata / rename operations to all selected photos."""

    changes_applied = pyqtSignal()

    def __init__(self, session, records: list[dict], parent=None):
        super().__init__(parent)
        self._session = session
        self._records = records

        photos = [r for r in records if r.get("file_type") == "photo"]
        n = len(records)
        self.setWindowTitle(
            f"Bulk Edit — {n:,} item{'s' if n != 1 else ''}"
        )
        self.resize(640, 720)
        self.setMinimumSize(520, 500)
        self.setStyleSheet(f"""
            QDialog   {{ background:#1e1e1e; color:#d4d4d4; }}
            QLabel    {{ color:#d4d4d4; }}
            QCheckBox {{ color:#d4d4d4; }}
            QRadioButton {{ color:#d4d4d4; font-size:12px; }}
            QProgressBar {{
                background:#2a2a2a; border:1px solid #444;
                border-radius:4px; height:8px; text-align:center; color:transparent;
            }}
            QProgressBar::chunk {{ background:#7c6af7; border-radius:3px; }}
            QPushButton {{
                background:#3a3a3a; color:#d4d4d4; border:1px solid #555;
                border-radius:4px; padding:4px 14px; font-size:12px;
            }}
            QPushButton:hover    {{ background:#4a4a4a; }}
            QPushButton:disabled {{ color:#555; border-color:#333; }}
            QPushButton#primary  {{
                background:#7c6af7; border-color:#7c6af7; color:#fff;
            }}
            QPushButton#primary:hover {{ background:#9480ff; }}
            {_INPUT_CSS}
        """)

        self._meta_cache: dict[int, dict] = {}
        self._build_ui()
        self._load_meta_cache()

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(8)

        # Summary
        photos = [r for r in self._records if r.get("file_type") == "photo"]
        n_p = len(photos)
        n_v = len(self._records) - n_p
        lbl = QLabel(
            f"Editing <b>{n_p}</b> photo{'s' if n_p != 1 else ''}"
            + (f" + <b>{n_v}</b> video{'s' if n_v != 1 else ''} "
               "(videos skipped for EXIF)" if n_v else "")
        )
        lbl.setStyleSheet("font-size:12px; color:#aaa;")
        root.addWidget(lbl)

        # Scrollable form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")

        form = QWidget()
        form.setStyleSheet("background:transparent;")
        self._form_layout = QVBoxLayout(form)
        self._form_layout.setContentsMargins(0, 0, 8, 0)
        self._form_layout.setSpacing(8)

        self._build_title_section()
        self._build_subject_section()
        self._build_location_section()
        self._build_tags_add_section()
        self._build_tags_remove_section()
        self._build_people_section()
        self._build_datetime_section()
        self._build_copyright_section()
        self._build_rename_section()
        self._build_rating_section()

        self._form_layout.addStretch()
        scroll.setWidget(form)
        root.addWidget(scroll, stretch=1)

        # Progress
        self._progress = QProgressBar()
        self._progress.hide()
        root.addWidget(self._progress)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color:#777; font-size:11px;")
        self._status_lbl.hide()
        root.addWidget(self._status_lbl)

        # Buttons
        btns = QDialogButtonBox()
        self._apply_btn = btns.addButton(
            f"Apply to {len(self._records):,} photo{'s' if len(self._records) != 1 else ''}",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self._apply_btn.setObjectName("primary")
        btns.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        btns.accepted.connect(self._apply)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    # ── Section builders ────────────────────────────────────────────────────

    def _build_title_section(self):
        self._sec_title = _Section("Title")
        w = QWidget(); w.setStyleSheet("background:transparent;")
        h = QHBoxLayout(w); h.setContentsMargins(0,0,0,0); h.setSpacing(8)
        self._title_input = QLineEdit()
        self._title_input.setPlaceholderText("Enter title for all photos…")
        h.addWidget(self._title_input, stretch=1)
        self._title_clear_chk = QCheckBox("Clear")
        self._title_clear_chk.setToolTip("Remove title from all photos instead of setting one")
        self._title_clear_chk.toggled.connect(
            lambda c: self._title_input.setEnabled(not c)
        )
        h.addWidget(self._title_clear_chk)
        self._sec_title.add(w)
        self._form_layout.addWidget(self._sec_title)

    def _build_subject_section(self):
        from memoria.ui.default_subjects import ALL_SUBJECTS, SUBJECT_CATEGORIES
        from PyQt6.QtWidgets import QCompleter, QMenu
        self._sec_subject = _Section("Subject")

        w = QWidget(); w.setStyleSheet("background:transparent;")
        h = QHBoxLayout(w); h.setContentsMargins(0,0,0,0); h.setSpacing(8)

        self._subject_input = QLineEdit()
        self._subject_input.setPlaceholderText("Subject for all photos…")
        comp = QCompleter(ALL_SUBJECTS, self._subject_input)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        self._subject_input.setCompleter(comp)
        h.addWidget(self._subject_input, stretch=1)

        drop = QPushButton("▾")
        drop.setFixedSize(26, 26)
        drop.setStyleSheet(
            "QPushButton{background:#3a3a3a;border:1px solid #555;"
            "border-radius:4px;color:#aaa;font-size:11px;padding:0;}"
            "QPushButton:hover{background:#4a4a4a;}"
        )
        def _show_menu():
            m = QMenu(self)
            m.setStyleSheet(
                "QMenu{background:#252526;color:#d4d4d4;border:1px solid #444;}"
                "QMenu::item{padding:4px 24px 4px 12px;font-size:12px;}"
                "QMenu::item:selected{background:#5a4fd4;color:#fff;}"
            )
            for cat, subs in SUBJECT_CATEGORIES:
                sub = m.addMenu(cat); sub.setStyleSheet(m.styleSheet())
                for s in subs:
                    sub.addAction(s).triggered.connect(
                        lambda _, v=s: self._subject_input.setText(v)
                    )
            m.exec(drop.mapToGlobal(drop.rect().bottomLeft()))
        drop.clicked.connect(_show_menu)
        h.addWidget(drop)

        self._subject_clear_chk = QCheckBox("Clear")
        self._subject_clear_chk.toggled.connect(
            lambda c: self._subject_input.setEnabled(not c)
        )
        h.addWidget(self._subject_clear_chk)

        self._sec_subject.add(w)
        self._form_layout.addWidget(self._sec_subject)

    def _build_location_section(self):
        self._sec_location = _Section("Location")

        self._location_combo = QComboBox()
        self._location_combo.setEditable(True)
        self._location_combo.lineEdit().setPlaceholderText("Enter location label…")
        # Populate from DB (expire_all for fresh data)
        try:
            self._session.expire_all()
            from memoria.database.models import Metadata as _M
            rows = (
                self._session.query(_M.location_label)
                .filter(_M.location_label.isnot(None), _M.location_label != "")
                .distinct().order_by(_M.location_label).all()
            )
            self._location_combo.addItem("")
            for r in rows:
                self._location_combo.addItem(r.location_label)
        except Exception:
            pass

        w = QWidget(); w.setStyleSheet("background:transparent;")
        h = QHBoxLayout(w); h.setContentsMargins(0,0,0,0); h.setSpacing(8)
        h.addWidget(self._location_combo, stretch=1)
        self._location_clear_chk = QCheckBox("Clear")
        self._location_clear_chk.toggled.connect(
            lambda c: self._location_combo.setEnabled(not c)
        )
        h.addWidget(self._location_clear_chk)
        self._sec_location.add(w)
        self._form_layout.addWidget(self._sec_location)

    def _build_tags_add_section(self):
        self._sec_tags_add = _Section("Tags — Add")
        self._tags_add_input = QLineEdit()
        self._tags_add_input.setPlaceholderText("tag1, tag2, tag3…")
        self._sec_tags_add.add(self._tags_add_input)
        lbl = QLabel("These tags are appended to each photo's existing tags.")
        lbl.setStyleSheet(_HINT_CSS)
        self._sec_tags_add.add(lbl)
        self._form_layout.addWidget(self._sec_tags_add)

    def _build_tags_remove_section(self):
        self._sec_tags_remove = _Section("Tags — Remove")
        self._tags_remove_input = QLineEdit()
        self._tags_remove_input.setPlaceholderText("tag1, tag2… (removed from any photo that has them)")
        self._sec_tags_remove.add(self._tags_remove_input)
        self._form_layout.addWidget(self._sec_tags_remove)

    def _build_people_section(self):
        self._sec_people = _Section("People — Assign")
        self._people_combo = QComboBox()
        try:
            from memoria.database.models import Person
            people = self._session.query(Person).order_by(Person.name).all()
            self._people_combo.addItem("— select person —", None)
            for p in people:
                self._people_combo.addItem(p.name, p.id)
        except Exception:
            self._people_combo.addItem("— no people found —", None)
        self._sec_people.add(self._people_combo)
        lbl = QLabel("Assigns this person to every selected photo (creates a face link).")
        lbl.setStyleSheet(_HINT_CSS)
        self._sec_people.add(lbl)
        self._form_layout.addWidget(self._sec_people)

    def _build_datetime_section(self):
        self._sec_datetime = _Section("Date / Time")

        # Radio: Shift vs Set
        self._dt_radio_shift = QRadioButton("Shift all dates by")
        self._dt_radio_set   = QRadioButton("Set all dates to")
        self._dt_radio_shift.setChecked(True)

        # Shift controls
        shift_row = QWidget(); shift_row.setStyleSheet("background:transparent;")
        sh = QHBoxLayout(shift_row); sh.setContentsMargins(0,0,0,0); sh.setSpacing(6)
        self._dt_shift_hours   = QSpinBox(); self._dt_shift_hours.setRange(-23, 23)
        self._dt_shift_minutes = QSpinBox(); self._dt_shift_minutes.setRange(-59, 59)
        self._dt_shift_hours.setSuffix(" h"); self._dt_shift_minutes.setSuffix(" min")
        self._dt_shift_hours.setFixedWidth(72); self._dt_shift_minutes.setFixedWidth(80)
        sh.addWidget(self._dt_radio_shift)
        sh.addWidget(self._dt_shift_hours)
        sh.addWidget(self._dt_shift_minutes)
        sh.addStretch()

        # Set-to controls
        set_row = QWidget(); set_row.setStyleSheet("background:transparent;")
        sv = QHBoxLayout(set_row); sv.setContentsMargins(0,0,0,0); sv.setSpacing(6)
        self._dt_set_edit = QDateTimeEdit()
        self._dt_set_edit.setDisplayFormat("dd/MM/yyyy  HH:mm")
        self._dt_set_edit.setDateTime(
            __import__("PyQt6.QtCore", fromlist=["QDateTime"]).QDateTime.currentDateTime()
        )
        self._dt_set_edit.setCalendarPopup(True)
        self._dt_set_edit.setFixedWidth(180)
        sv.addWidget(self._dt_radio_set)
        sv.addWidget(self._dt_set_edit)
        sv.addStretch()

        def _sync_dt_mode():
            shift = self._dt_radio_shift.isChecked()
            self._dt_shift_hours.setEnabled(shift)
            self._dt_shift_minutes.setEnabled(shift)
            self._dt_set_edit.setEnabled(not shift)
        self._dt_radio_shift.toggled.connect(_sync_dt_mode)
        _sync_dt_mode()

        self._sec_datetime.add(shift_row)
        self._sec_datetime.add(set_row)
        lbl = QLabel("Useful for timezone corrections or fixing a wrong camera clock.")
        lbl.setStyleSheet(_HINT_CSS)
        self._sec_datetime.add(lbl)
        self._form_layout.addWidget(self._sec_datetime)

    def _build_copyright_section(self):
        self._sec_copyright = _Section("Copyright / Creator")
        self._copyright_artist = QLineEdit()
        self._copyright_artist.setPlaceholderText("Photographer name  (EXIF Artist)")
        self._copyright_notice = QLineEdit()
        self._copyright_notice.setPlaceholderText("© 2024 Your Name  (EXIF Copyright)")
        self._sec_copyright.add_row("Artist",    self._copyright_artist)
        self._sec_copyright.add_row("Copyright", self._copyright_notice)
        self._form_layout.addWidget(self._sec_copyright)

    def _build_rename_section(self):
        self._sec_rename = _Section("Filename Rename")

        # Template input
        tmpl_row = QWidget(); tmpl_row.setStyleSheet("background:transparent;")
        th = QHBoxLayout(tmpl_row); th.setContentsMargins(0,0,0,0); th.setSpacing(6)
        self._rename_template = QLineEdit()
        self._rename_template.setPlaceholderText("{date}_{time}_{subject}")
        self._rename_template.setText("{date}_{time}_{subject}")
        self._rename_template.textChanged.connect(self._update_rename_preview)
        th.addWidget(self._rename_template, stretch=1)
        self._sec_rename.add(tmpl_row)

        # Token buttons
        tokens_row = QWidget(); tokens_row.setStyleSheet("background:transparent;")
        tw = QHBoxLayout(tokens_row); tw.setContentsMargins(0,0,0,0); tw.setSpacing(4)
        tw.addWidget(QLabel("Insert:"))
        for token, tip in _RENAME_TOKENS:
            btn = QPushButton(token)
            btn.setFixedHeight(20)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                "QPushButton{background:#2a2a2a;color:#aaa;border:1px solid #444;"
                "border-radius:3px;font-size:10px;padding:0 4px;}"
                "QPushButton:hover{color:#fff;background:#3a3a3a;}"
            )
            btn.clicked.connect(lambda _, t=token: self._insert_token(t))
            tw.addWidget(btn)
        tw.addStretch()
        self._sec_rename.add(tokens_row)

        # Conflict handling
        conf_row = QWidget(); conf_row.setStyleSheet("background:transparent;")
        ch = QHBoxLayout(conf_row); ch.setContentsMargins(0,0,0,0); ch.setSpacing(8)
        ch.addWidget(QLabel("If name exists:"))
        self._rename_conflict = QComboBox()
        self._rename_conflict.addItem("Add suffix  (_1, _2…)", "suffix")
        self._rename_conflict.addItem("Skip file",             "skip")
        self._rename_conflict.setFixedWidth(160)
        ch.addWidget(self._rename_conflict)
        ch.addStretch()
        self._sec_rename.add(conf_row)

        # Preview table
        prev_lbl = QLabel("Preview (first 8 files):")
        prev_lbl.setStyleSheet("color:#888; font-size:11px;")
        self._sec_rename.add(prev_lbl)

        self._rename_preview = QTableWidget(0, 2)
        self._rename_preview.setHorizontalHeaderLabels(["Current filename", "New filename"])
        self._rename_preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._rename_preview.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._rename_preview.verticalHeader().hide()
        self._rename_preview.setShowGrid(False)
        self._rename_preview.setAlternatingRowColors(True)
        self._rename_preview.setFixedHeight(140)
        self._rename_preview.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._rename_preview.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._rename_preview.verticalHeader().setDefaultSectionSize(20)
        self._rename_preview.setStyleSheet("""
            QTableWidget {
                background:#1e1e1e; border:1px solid #333; font-size:11px; color:#d4d4d4;
            }
            QTableWidget::item { padding:1px 6px; border:none; }
            QTableWidget::item:alternate { background:#222; }
            QHeaderView::section {
                background:#252526; color:#666; border:none;
                border-bottom:1px solid #333; padding:2px 6px; font-size:10px;
            }
        """)
        self._sec_rename.add(self._rename_preview)
        self._sec_rename._chk.stateChanged.connect(
            lambda _: self._update_rename_preview()
        )
        self._form_layout.addWidget(self._sec_rename)

    def _build_rating_section(self):
        self._sec_rating = _Section("Rating  ★")
        lbl = QLabel("Star rating support coming in a future update.")
        lbl.setStyleSheet("color:#555; font-size:11px; font-style:italic;")
        self._sec_rating.add(lbl)
        self._sec_rating._chk.setEnabled(False)
        self._form_layout.addWidget(self._sec_rating)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _load_meta_cache(self):
        """Pre-load metadata for all records into a dict keyed by file_id."""
        try:
            from memoria.database.models import Metadata
            ids = [r["id"] for r in self._records]
            rows = (
                self._session.query(Metadata)
                .filter(Metadata.file_id.in_(ids))
                .all()
            )
            for m in rows:
                self._meta_cache[m.file_id] = {
                    "title":        m.title,
                    "subject":      m.subject,
                    "location_label": m.location_label,
                    "date_taken":   m.date_taken,
                }
        except Exception as e:
            log.warning(f"Meta cache load failed: {e}")

    def _insert_token(self, token: str):
        self._rename_template.insert(token)
        self._rename_template.setFocus()

    def _update_rename_preview(self):
        template = self._rename_template.text().strip()
        self._rename_preview.setRowCount(0)
        if not template:
            return
        preview_records = self._records[:8]
        for seq, rec in enumerate(preview_records, start=1):
            meta = self._meta_cache.get(rec["id"])
            old_name = rec["filename"]
            ext      = Path(rec["filepath"]).suffix
            new_stem = _apply_rename_template(template, rec, meta, seq)
            new_name = new_stem + ext

            row = self._rename_preview.rowCount()
            self._rename_preview.insertRow(row)
            old_item = QTableWidgetItem(old_name)
            new_item = QTableWidgetItem(new_name)
            changed = old_name != new_name
            from PyQt6.QtGui import QColor
            new_item.setForeground(
                QColor("#a6e3a1") if changed else QColor("#555")
            )
            self._rename_preview.setItem(row, 0, old_item)
            self._rename_preview.setItem(row, 1, new_item)

    # ── Apply ────────────────────────────────────────────────────────────────

    def _apply(self):
        active_sections = [
            s for s in (
                self._sec_title, self._sec_subject, self._sec_location,
                self._sec_tags_add, self._sec_tags_remove, self._sec_people,
                self._sec_datetime, self._sec_copyright, self._sec_rename,
            )
            if s.active
        ]
        if not active_sections:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Nothing to do",
                "Tick at least one section to apply.")
            return

        self._apply_btn.setEnabled(False)
        total = len(self._records)
        self._progress.setRange(0, total)
        self._progress.setValue(0)
        self._progress.show()
        self._status_lbl.show()

        changed = 0
        errors  = 0
        for i, rec in enumerate(self._records):
            self._progress.setValue(i + 1)
            self._status_lbl.setText(f"Processing {i+1}/{total}  {rec['filename']}")
            QApplication.processEvents()
            try:
                self._apply_to_record(rec)
                changed += 1
            except Exception as e:
                log.error(f"Bulk edit failed for {rec['filename']}: {e}",
                          exc_info=True)
                self._session.rollback()
                errors += 1

        msg = f"Done — {changed:,} file{'s' if changed != 1 else ''} updated."
        if errors:
            msg += f"  ({errors} error{'s' if errors != 1 else ''})"
        self._status_lbl.setText(msg)
        self._status_lbl.setStyleSheet(
            "color:#f38ba8; font-size:11px;" if errors
            else "color:#a6e3a1; font-size:11px;"
        )
        self.changes_applied.emit()
        self._apply_btn.setEnabled(True)

    def _apply_to_record(self, rec: dict):
        from memoria.database.models import (
            Metadata, Tag, FileTag, FilePeople, File,
        )
        file_id  = rec["id"]
        filepath = rec["filepath"]
        is_photo = rec.get("file_type") == "photo"

        meta = (
            self._session.query(Metadata)
            .filter_by(file_id=file_id).first()
        )
        if meta is None:
            meta = Metadata(file_id=file_id)
            self._session.add(meta)

        dirty_exif_ts = False   # title/subject changed
        dirty_tags    = False
        dirty_exif_cr = False   # copyright changed

        # ── Title ──────────────────────────────────────────────────────
        if self._sec_title.active:
            if self._title_clear_chk.isChecked():
                meta.title = None
            else:
                meta.title = self._title_input.text().strip() or None
            dirty_exif_ts = True

        # ── Subject ────────────────────────────────────────────────────
        if self._sec_subject.active:
            if self._subject_clear_chk.isChecked():
                meta.subject = None
            else:
                meta.subject = self._subject_input.text().strip() or None
            dirty_exif_ts = True

        # ── Location ───────────────────────────────────────────────────
        if self._sec_location.active:
            if self._location_clear_chk.isChecked():
                meta.location_label = None
            else:
                meta.location_label = (
                    self._location_combo.currentText().strip() or None
                )

        # ── Tags — Add ─────────────────────────────────────────────────
        if self._sec_tags_add.active:
            labels = [
                t.strip()
                for t in self._tags_add_input.text().split(",")
                if t.strip()
            ]
            for label in labels:
                tag = self._session.query(Tag).filter_by(label=label).first()
                if tag is None:
                    tag = Tag(label=label)
                    self._session.add(tag)
                    self._session.flush()
                exists = (
                    self._session.query(FileTag)
                    .filter_by(file_id=file_id, tag_id=tag.id).first()
                )
                if not exists:
                    self._session.add(FileTag(file_id=file_id, tag_id=tag.id))
            dirty_tags = bool(labels)

        # ── Tags — Remove ──────────────────────────────────────────────
        if self._sec_tags_remove.active:
            labels = [
                t.strip()
                for t in self._tags_remove_input.text().split(",")
                if t.strip()
            ]
            for label in labels:
                tag = self._session.query(Tag).filter_by(label=label).first()
                if tag:
                    self._session.query(FileTag).filter_by(
                        file_id=file_id, tag_id=tag.id
                    ).delete()
            dirty_tags = dirty_tags or bool(labels)

        # ── People ─────────────────────────────────────────────────────
        if self._sec_people.active:
            person_id = self._people_combo.currentData()
            if person_id is not None:
                exists = (
                    self._session.query(FilePeople)
                    .filter_by(file_id=file_id, person_id=person_id).first()
                )
                if not exists:
                    self._session.add(
                        FilePeople(file_id=file_id, person_id=person_id)
                    )

        # ── Date / Time ────────────────────────────────────────────────
        if self._sec_datetime.active:
            if self._dt_radio_shift.isChecked():
                hrs = self._dt_shift_hours.value()
                mins = self._dt_shift_minutes.value()
                if (hrs or mins) and meta.date_taken:
                    meta.date_taken = (
                        meta.date_taken
                        + timedelta(hours=hrs, minutes=mins)
                    )
            else:
                qdt = self._dt_set_edit.dateTime()
                meta.date_taken = datetime(
                    qdt.date().year(), qdt.date().month(), qdt.date().day(),
                    qdt.time().hour(), qdt.time().minute(), qdt.time().second(),
                )

        # ── Copyright ──────────────────────────────────────────────────
        if self._sec_copyright.active:
            artist    = self._copyright_artist.text().strip()
            copyright_ = self._copyright_notice.text().strip()
            if artist or copyright_:
                dirty_exif_cr = True

        self._session.commit()

        # ── EXIF writes ────────────────────────────────────────────────
        if is_photo and Path(filepath).exists():
            if dirty_exif_ts:
                self._write_title_subject(
                    filepath, meta.title, meta.subject
                )
            if dirty_tags:
                from memoria.exif_writer import write_tags_to_file
                all_tags = [
                    r.label
                    for r in (
                        self._session.query(Tag.label)
                        .join(FileTag, FileTag.tag_id == Tag.id)
                        .filter(FileTag.file_id == file_id)
                        .order_by(Tag.label).all()
                    )
                ]
                write_tags_to_file(filepath, all_tags)
            if dirty_exif_cr:
                self._write_copyright(
                    filepath,
                    self._copyright_artist.text().strip(),
                    self._copyright_notice.text().strip(),
                )

        # ── Filename rename ────────────────────────────────────────────
        if self._sec_rename.active:
            template  = self._rename_template.text().strip()
            conflict  = self._rename_conflict.currentData()
            seq       = self._records.index(rec) + 1
            meta_dict = self._meta_cache.get(file_id)
            if template:
                self._rename_file(rec, template, seq, conflict, meta_dict)

        # Auto-rename check
        from memoria.file_status import maybe_auto_rename
        maybe_auto_rename(file_id, self._session)

    # ── EXIF helpers ─────────────────────────────────────────────────────────

    def _write_title_subject(self, filepath: str,
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
            log.warning(f"exiftool title/subject write failed: {e}")

    def _write_copyright(self, filepath: str, artist: str, copyright_: str):
        import subprocess
        from memoria.exif_writer import _exiftool_path
        tool = _exiftool_path()
        if not tool:
            return
        args = [tool, "-overwrite_original", "-charset", "UTF8"]
        if artist:
            args += [f"-EXIF:Artist={artist}", f"-XMP-dc:Creator={artist}"]
        if copyright_:
            args += [f"-EXIF:Copyright={copyright_}", f"-XMP-dc:Rights={copyright_}"]
        args.append(filepath)
        try:
            subprocess.run(args, capture_output=True, timeout=15)
        except Exception as e:
            log.warning(f"exiftool copyright write failed: {e}")

    def _rename_file(self, rec: dict, template: str, seq: int,
                     conflict: str, meta: dict | None):
        from memoria.database.models import File
        filepath = Path(rec["filepath"])
        if not filepath.exists():
            return
        ext      = filepath.suffix
        new_stem = _apply_rename_template(template, rec, meta, seq)
        new_path = filepath.parent / (new_stem + ext)

        if new_path == filepath:
            return  # nothing to do

        # Conflict resolution
        if new_path.exists():
            if conflict == "skip":
                return
            # Add suffix
            counter = 1
            base = new_path.stem
            while new_path.exists():
                new_path = filepath.parent / f"{base}_{counter}{ext}"
                counter += 1

        try:
            os.rename(filepath, new_path)
            file_row = self._session.query(File).get(rec["id"])
            if file_row:
                file_row.filepath = str(new_path)
                file_row.filename = new_path.name
                self._session.commit()
            rec["filepath"] = str(new_path)
            rec["filename"] = new_path.name
        except OSError as e:
            log.warning(f"Rename failed {filepath} → {new_path}: {e}")
