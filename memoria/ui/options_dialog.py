"""
Options Dialog
──────────────
Left column: section list.
Right column: stacked pages, one per section.

Layout inspired by Obsidian settings:
  • Items grouped inside a dark rounded card
  • Name + description left-aligned, control right-aligned
  • Thin separator between rows within a group
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDialogButtonBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSlider, QSpinBox, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

# ── Shared layout helpers ─────────────────────────────────────────────────────

_GROUP_BG   = "#252526"
_PAGE_BG    = "#1e1e1e"
_TITLE_CSS  = "color:#e0e0e0; font-size:13px; font-weight:600; background:transparent;"
_DESC_CSS   = "color:#777; font-size:11px; background:transparent;"
_SEP_CSS    = "background:#333;"


class _ToggleSwitch(QWidget):
    """
    iOS-style toggle switch.
    Track is accent-coloured when on, grey when off.
    Thumb is a white circle that sits left (off) or right (on).
    """
    toggled = pyqtSignal(bool)

    _W, _H, _THUMB = 44, 24, 18   # track width, track height, thumb diameter

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(self._W, self._H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, v: bool):
        if self._checked != v:
            self._checked = v
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self.toggled.emit(self._checked)
            self.update()

    def paintEvent(self, _):
        from memoria.ui.theme import accent
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H, T = self._W, self._H, self._THUMB
        pad = (H - T) // 2

        # Track
        track = QPainterPath()
        track.addRoundedRect(0, 0, W, H, H / 2, H / 2)
        p.fillPath(track, QColor(accent() if self._checked else "#555555"))

        # Thumb
        thumb_x = W - pad - T if self._checked else pad
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(thumb_x, pad, T, T)
        p.end()


def _slider_widget(slider: QSlider, fmt: str = "{}") -> QWidget:
    """Value label stacked above the slider (right-aligned), slider below."""
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    col = QVBoxLayout(w)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(3)

    lbl = QLabel(fmt.format(slider.value()))
    lbl.setStyleSheet("color:#d4d4d4; font-size:12px; background:transparent;")
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    slider.valueChanged.connect(lambda v, l=lbl: l.setText(fmt.format(v)))

    col.addWidget(lbl)
    col.addWidget(slider)
    return w


class _SettingRow(QWidget):
    """
    One row inside a settings group:
      [  Title          ]  [ control ]
      [  Description    ]
    """
    def __init__(self, title: str, description: str,
                 control: QWidget, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(16)

        # Left: title + description stacked
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(_TITLE_CSS)
        text_col.addWidget(title_lbl)

        desc_lbl = QLabel(description)
        desc_lbl.setStyleSheet(_DESC_CSS)
        desc_lbl.setWordWrap(True)
        text_col.addWidget(desc_lbl)

        row.addLayout(text_col, stretch=1)

        # Right: control — vertically centred
        control.setParent(self)
        row.addWidget(control, alignment=Qt.AlignmentFlag.AlignVCenter)


class _SettingGroup(QWidget):
    """
    Dark rounded card that holds one or more _SettingRow widgets
    separated by thin lines.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        # WA_StyledBackground makes plain QWidget actually paint its bg from the stylesheet
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("settingGroup")
        self.setStyleSheet(
            f"QWidget#settingGroup {{ background:{_GROUP_BG}; border-radius:8px; }}"
        )
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._rows: list[QWidget] = []

    def add_row(self, title: str, description: str, control: QWidget):
        if self._rows:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setFixedHeight(1)
            sep.setStyleSheet(f"background:{_SEP_CSS[12:-1]}; border:none;")
            self._layout.addWidget(sep)

        row = _SettingRow(title, description, control)
        self._layout.addWidget(row)
        self._rows.append(row)
        return row


def _page_layout() -> tuple[QWidget, QVBoxLayout]:
    """Return a page widget + its VBoxLayout ready for group cards."""
    w = QWidget()
    w.setStyleSheet(f"background:{_PAGE_BG};")
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(16)
    return w, v


def _section_header(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet("color:#aaa; font-size:11px; font-weight:600; "
                      "padding:0 0 4px 0; background:transparent;")
    return lbl


# ── Subject manager widget ────────────────────────────────────────────────────

class _SubjectManagerWidget(QWidget):
    """
    Two-panel editor for default subjects:
      Left  — category list
      Right — subjects for selected category + add/delete controls
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")

        # Work on a deep copy so changes only persist on save()
        from memoria.ui.default_subjects import get_categories
        self._data: list[tuple[str, list[str]]] = [
            (cat, list(subs)) for cat, subs in get_categories()
        ]

        # Vertical layout: columns at top, controls at bottom
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ── Two-column layout (equal width) ────────────────────────────────
        cols_widget = QWidget()
        cols_widget.setStyleSheet("background:transparent;")
        cols_h = QHBoxLayout(cols_widget)
        cols_h.setContentsMargins(0, 0, 0, 0)
        cols_h.setSpacing(8)

        # Left: category list — slightly lighter than card background so it's visible
        left = QWidget()
        left.setStyleSheet("background:#2d2d2d; border-radius:6px;")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 4, 0, 4)
        lv.setSpacing(0)

        # ~14 visible items; scroll for more
        _LIST_H = 300
        _list_css = f"""
            QListWidget {{
                background: transparent; border: none; outline: none;
                font-size: 12px; color: #d4d4d4;
            }}
            QListWidget::item {{
                padding: 2px 10px;
                min-height: 18px;
            }}
            QListWidget::item:selected {{ background: #37373d; color: #fff; }}
            QListWidget::item:hover:!selected {{ background: #2d2d2d; }}
        """

        self._cat_list = QListWidget()
        self._cat_list.setFixedHeight(_LIST_H)
        self._cat_list.setStyleSheet(_list_css)
        for cat, _ in self._data:
            self._cat_list.addItem(cat)
        self._cat_list.currentRowChanged.connect(self._on_cat_changed)
        lv.addWidget(self._cat_list)
        cols_h.addWidget(left, stretch=1)

        # Right: subject list — same lighter bg
        right = QWidget()
        right.setStyleSheet("background:#2d2d2d; border-radius:6px;")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 4, 0, 4)
        rv.setSpacing(0)

        self._subj_list = QListWidget()
        self._subj_list.setFixedHeight(_LIST_H)
        self._subj_list.setStyleSheet(_list_css)
        rv.addWidget(self._subj_list)
        cols_h.addWidget(right, stretch=1)

        layout.addWidget(cols_widget)

        # ── Controls below columns (input + Add / Delete) ──────────────────
        layout.addSpacing(6)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)
        ctrl_row.setContentsMargins(0, 0, 0, 0)

        self._new_input = QLineEdit()
        self._new_input.setPlaceholderText("New subject…")
        self._new_input.setFixedHeight(26)
        self._new_input.returnPressed.connect(self._add_subject)
        ctrl_row.addWidget(self._new_input, stretch=1)

        add_btn = QPushButton("Add")
        add_btn.setFixedHeight(26)
        add_btn.setMinimumWidth(56)
        add_btn.setStyleSheet(
            "QPushButton{background:#3a3a3a;color:#d4d4d4;border:1px solid #555;"
            "border-radius:4px;padding:2px 8px;font-size:12px;}"
            "QPushButton:hover{background:#4a4a4a;}"
        )
        add_btn.clicked.connect(self._add_subject)
        ctrl_row.addWidget(add_btn)

        del_btn = QPushButton("Delete")
        del_btn.setFixedHeight(26)
        del_btn.setMinimumWidth(60)
        del_btn.setStyleSheet(
            "QPushButton{background:#3a2020;color:#f38ba8;border:1px solid #5a3030;"
            "border-radius:4px;padding:2px 8px;font-size:12px;}"
            "QPushButton:hover{background:#5a2020;}"
        )
        del_btn.clicked.connect(self._delete_subject)
        ctrl_row.addWidget(del_btn)

        layout.addLayout(ctrl_row)

        # Select first category
        if self._cat_list.count():
            self._cat_list.setCurrentRow(0)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _current_cat_idx(self) -> int:
        return self._cat_list.currentRow()

    def _on_cat_changed(self, idx: int):
        self._subj_list.clear()
        if 0 <= idx < len(self._data):
            for s in self._data[idx][1]:
                self._subj_list.addItem(s)

    def _add_subject(self):
        text = self._new_input.text().strip()
        if not text:
            return
        idx = self._current_cat_idx()
        if idx < 0:
            return
        cat, subs = self._data[idx]
        if text in subs:
            return
        subs.append(text)
        self._data[idx] = (cat, subs)
        self._subj_list.addItem(text)
        self._new_input.clear()

    def _delete_subject(self):
        idx = self._current_cat_idx()
        sel = self._subj_list.currentRow()
        if idx < 0 or sel < 0:
            return
        subject = self._subj_list.item(sel).text()
        reply = QMessageBox.question(
            self, "Delete subject",
            f"Remove \"{subject}\" from this category?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        cat, subs = self._data[idx]
        subs.remove(subject)
        self._data[idx] = (cat, subs)
        self._subj_list.takeItem(sel)

    def save(self):
        """Persist changes to settings."""
        from memoria.ui.default_subjects import save_categories
        save_categories(self._data)


# ── Section pages ─────────────────────────────────────────────────────────────

class _GeneralPage(QWidget):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)

        page, v = _page_layout()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)

        v.addWidget(_section_header("General"))

        group = _SettingGroup()

        # Columns — dropdown 3-12 (same width as the toggle switch below)
        self._cols = QComboBox()
        self._cols.setFixedWidth(44)
        for n in range(3, 13):
            self._cols.addItem(str(n), n)
        cur = settings.get("columns", 5)
        self._cols.setCurrentIndex(max(0, min(cur - 3, 9)))
        group.add_row(
            "Default grid columns",
            "Number of columns shown in the photo grid when the app starts.",
            self._cols,
        )

        # Show extensions — toggle switch
        self._exts = _ToggleSwitch(checked=settings.get("show_extensions", True))
        group.add_row(
            "Show file extensions",
            "Display the file extension (e.g. .jpg) in each photo card label.",
            self._exts,
        )

        v.addWidget(group)
        v.addStretch()

    def apply(self, settings: dict):
        settings["columns"]         = self._cols.currentData()
        settings["show_extensions"] = self._exts.isChecked()


class _EditorPage(QWidget):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)

        page, v = _page_layout()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)

        v.addWidget(_section_header("Editor"))

        group = _SettingGroup()

        # JPEG quality — horizontal slider 60-100 %
        self._quality = QSlider(Qt.Orientation.Horizontal)
        self._quality.setRange(60, 100)
        self._quality.setValue(settings.get("jpeg_quality", 100))
        self._quality.setFixedWidth(200)
        group.add_row(
            "JPEG save quality",
            "Compression quality used when saving rotated JPEG files. "
            "Higher values preserve more detail.",
            _slider_widget(self._quality, "{} %"),
        )

        # Auto-rename format
        self._fmt = QLineEdit(settings.get("rename_format", "%y-%m-%d_%H-%M_{subject}"))
        self._fmt.setFixedWidth(200)
        self._fmt.setToolTip(
            "%y=year(2)  %Y=year(4)  %m=month  %d=day  %H=hour  %M=minute  {subject}"
        )
        group.add_row(
            "Auto-rename format",
            "Template for the filename when a photo is auto-renamed. "
            "Tokens: %y %m %d %H %M for date/time, {subject} for the subject.",
            self._fmt,
        )

        # Auto-write EXIF
        self._auto_exif = _ToggleSwitch(checked=settings.get("auto_write_exif", False))
        group.add_row(
            "Auto-write metadata to files",
            "When enabled, title and subject changes are immediately written to the "
            "file's EXIF data. When disabled, changes are saved to the database only "
            "and can be written via the Activity Log.",
            self._auto_exif,
        )

        v.addWidget(group)
        v.addStretch()

    def apply(self, settings: dict):
        settings["jpeg_quality"]   = self._quality.value()
        settings["rename_format"]  = self._fmt.text().strip()
        settings["auto_write_exif"] = self._auto_exif.isChecked()


class _AppearancePage(QWidget):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self._colour = settings.get("accent_colour", "#7c6af7")
        self._overlay_on = settings.get("status_overlay", False)

        page, v = _page_layout()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)

        v.addWidget(_section_header("Appearance"))

        group = _SettingGroup()

        # Control: reset button + colour swatch
        ctrl = QWidget()
        ctrl.setStyleSheet("background:transparent;")
        ctrl_row = QHBoxLayout(ctrl)
        ctrl_row.setContentsMargins(0, 0, 0, 0)
        ctrl_row.setSpacing(6)

        from memoria.ui.fluent_icons import fi, FONT_NAME
        self._reset_btn = QPushButton(fi.REFRESH)
        self._reset_btn.setFont(QFont(FONT_NAME, 14))
        self._reset_btn.setFixedSize(28, 28)
        self._reset_btn.setToolTip("Reset to default colour")
        self._reset_btn.setStyleSheet(
            "QPushButton { background:transparent; border:none; color:#ffffff; padding:0; }"
            "QPushButton:hover { color:#aaaaaa; }"
            "QPushButton:pressed { color:#666666; }"
        )
        self._reset_btn.clicked.connect(self._reset_colour)
        ctrl_row.addWidget(self._reset_btn)

        self._swatch = QPushButton()
        self._swatch.setFixedSize(32, 32)
        self._swatch.setToolTip("Click to choose a colour")
        self._swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._swatch.clicked.connect(self._pick_colour)
        self._update_swatch()
        ctrl_row.addWidget(self._swatch)

        group.add_row(
            "Highlight colour",
            "Accent colour used for buttons, scrollbars, focus rings and "
            "selections throughout the app. Changes apply immediately.",
            ctrl,
        )

        v.addWidget(group)

        # ── Status overlay card ───────────────────────────────────────────────
        overlay_group = _SettingGroup()
        self._overlay_switch = _ToggleSwitch(checked=self._overlay_on)
        overlay_group.add_row(
            "Status overlay",
            "Show a completion-status dot bar on every photo thumbnail. "
            "Green = fields satisfied, Red = missing, Amber = intentionally incomplete. "
            "Click the bar to open the quick-edit dialog.",
            self._overlay_switch,
        )
        v.addWidget(overlay_group)
        v.addStretch()

    def _pick_colour(self):
        col = QColorDialog.getColor(QColor(self._colour), self, "Choose highlight colour")
        if col.isValid():
            self._colour = col.name()
            self._update_swatch()
            self._live_apply()

    def _reset_colour(self):
        self._colour = "#7c6af7"
        self._update_swatch()
        self._live_apply()

    def _update_swatch(self):
        self._swatch.setStyleSheet(
            f"QPushButton {{ background:{self._colour}; border:1px solid #555; "
            f"border-radius:16px; }}"
            f"QPushButton:hover {{ border-color:#ccc; border-width:2px; }}"
        )

    def _live_apply(self):
        from memoria.ui.theme import set_accent
        set_accent(self._colour)

    def apply(self, settings: dict):
        settings["accent_colour"] = self._colour
        settings["status_overlay"] = self._overlay_switch.isChecked()
        self._live_apply()


class _MetadataPage(QWidget):
    """Options page — default subjects for the EXIF Subject field."""

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #1e1e1e; }")
        outer.addWidget(scroll)

        page, v = _page_layout()
        scroll.setWidget(page)

        v.addWidget(_section_header("Metadata"))

        # Subject manager inside a card
        card = _SettingGroup()
        card._layout.setContentsMargins(16, 12, 16, 12)
        card._layout.setSpacing(6)

        title_lbl = QLabel("Default Subjects")
        title_lbl.setStyleSheet(_TITLE_CSS)
        card._layout.addWidget(title_lbl)

        desc_lbl = QLabel(
            "Manage subject categories and values used in the EXIF Subject field. "
            "Select a category on the left, then add or remove subjects on the right."
        )
        desc_lbl.setStyleSheet(_DESC_CSS)
        desc_lbl.setWordWrap(True)
        card._layout.addWidget(desc_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#333; border:none;")
        card._layout.addWidget(sep)

        self._subj_mgr = _SubjectManagerWidget()
        card._layout.addWidget(self._subj_mgr)

        v.addWidget(card)
        v.addStretch()

    def apply(self, settings: dict):
        self._subj_mgr.save()


class _AIPage(QWidget):
    """Options page — face detection and matching thresholds."""

    _MODELS    = ["ArcFace", "Facenet512", "VGG-Face", "DeepFace", "OpenFace"]
    _DETECTORS = ["retinaface", "mtcnn", "opencv", "ssd", "dlib"]

    _DEFAULTS = {
        "face_model":        "ArcFace",
        "detector_backend":  "retinaface",
        "match_threshold":   0.6,
        "cluster_threshold": 0.4,
        "min_cluster_size":  2,
    }

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #1e1e1e; }")
        outer.addWidget(scroll)

        page, v = _page_layout()
        scroll.setWidget(page)

        v.addWidget(_section_header("Caption Generation"))

        # ── API configuration ──────────────────────────────────────────
        api_group = _SettingGroup()

        # Provider
        self._provider_combo = QComboBox()
        self._provider_combo.setFixedWidth(140)
        self._provider_combo.addItem("Google Gemini", "gemini")
        idx = self._provider_combo.findData(settings.get("ai_provider", "gemini"))
        self._provider_combo.setCurrentIndex(max(0, idx))
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        api_group.add_row(
            "AI provider",
            "Vision AI service used to generate titles and subjects.",
            self._provider_combo,
        )

        # Model
        self._caption_model_combo = QComboBox()
        self._caption_model_combo.setFixedWidth(200)
        from memoria.database.db import get_app_setting
        self._refresh_caption_models(get_app_setting("ai_caption_model", "gemini-2.0-flash-lite"))
        api_group.add_row(
            "Caption model",
            "Model used for photo analysis. Faster models cost less; "
            "Pro models produce richer descriptions.",
            self._caption_model_combo,
        )

        # API key
        key_widget = QWidget()
        key_widget.setStyleSheet("background:transparent;")
        key_row = QHBoxLayout(key_widget)
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.setSpacing(6)
        from memoria.database.db import get_app_setting
        self._api_key_input = QLineEdit(get_app_setting("ai_api_key", ""))
        self._api_key_input.setFixedWidth(260)
        self._api_key_input.setPlaceholderText("Paste API key here…")
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        key_row.addWidget(self._api_key_input)
        self._show_key_btn = QPushButton("Show")
        self._show_key_btn.setFixedSize(52, 26)
        self._show_key_btn.setCheckable(True)
        self._show_key_btn.setStyleSheet(
            "QPushButton { background:#3a3a3a; color:#aaa; border:1px solid #555; "
            "border-radius:4px; font-size:11px; }"
            "QPushButton:checked { color:#fff; }"
        )
        self._show_key_btn.clicked.connect(
            lambda checked: self._api_key_input.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        key_row.addWidget(self._show_key_btn)
        api_group.add_row(
            "API key",
            "Key is stored locally in ui_settings.json and never sent anywhere "
            "except the selected provider.",
            key_widget,
        )

        v.addWidget(api_group)

        v.addWidget(_section_header("AI & Face Detection"))

        # ── Detection settings ─────────────────────────────────────────
        detect_group = _SettingGroup()

        self._model_combo = QComboBox()
        self._model_combo.setFixedWidth(140)
        for m in self._MODELS:
            self._model_combo.addItem(m)
        idx = self._model_combo.findText(settings.get("face_model", self._DEFAULTS["face_model"]))
        self._model_combo.setCurrentIndex(max(0, idx))
        detect_group.add_row(
            "Face recognition model",
            "The neural network used to generate face embeddings. "
            "ArcFace gives the best accuracy. Changing this requires a full re-scan.",
            self._model_combo,
        )

        self._detector_combo = QComboBox()
        self._detector_combo.setFixedWidth(140)
        for d in self._DETECTORS:
            self._detector_combo.addItem(d)
        idx = self._detector_combo.findText(settings.get("detector_backend", self._DEFAULTS["detector_backend"]))
        self._detector_combo.setCurrentIndex(max(0, idx))
        detect_group.add_row(
            "Face detector",
            "Algorithm used to locate faces within photos. "
            "RetinaFace is the most accurate; OpenCV is fastest. Changing this requires a full re-scan.",
            self._detector_combo,
        )

        v.addWidget(detect_group)

        # ── Matching & clustering ──────────────────────────────────────
        v.addWidget(_section_header("Matching & Clustering"))

        thresh_group = _SettingGroup()

        # Match threshold slider (30–90, stored as float 0.30–0.90)
        self._match_slider = QSlider(Qt.Orientation.Horizontal)
        self._match_slider.setRange(30, 90)
        self._match_slider.setValue(int(settings.get("match_threshold", self._DEFAULTS["match_threshold"]) * 100))
        self._match_slider.setFixedWidth(200)
        thresh_group.add_row(
            "Face match sensitivity",
            "How closely a face must resemble a known person to be assigned to them. "
            "Lower = stricter (fewer false matches). Higher = more lenient (catches more matches but may confuse similar faces). Default: 0.60.",
            self._float_slider_widget(self._match_slider),
        )

        # Cluster threshold slider (20–80)
        self._cluster_slider = QSlider(Qt.Orientation.Horizontal)
        self._cluster_slider.setRange(20, 80)
        self._cluster_slider.setValue(int(settings.get("cluster_threshold", self._DEFAULTS["cluster_threshold"]) * 100))
        self._cluster_slider.setFixedWidth(200)
        thresh_group.add_row(
            "Cluster grouping sensitivity",
            "How tightly faces must match to be grouped into the same cluster. "
            "Lower = tighter groups (fewer faces per cluster). Higher = looser groups (larger clusters, more risk of mixing people). Default: 0.40.",
            self._float_slider_widget(self._cluster_slider),
        )

        # Min cluster size dropdown
        self._min_size_combo = QComboBox()
        self._min_size_combo.setFixedWidth(60)
        for n in range(1, 11):
            self._min_size_combo.addItem(str(n), n)
        cur = settings.get("min_cluster_size", self._DEFAULTS["min_cluster_size"])
        self._min_size_combo.setCurrentIndex(max(0, int(cur) - 1))
        thresh_group.add_row(
            "Minimum cluster size",
            "Clusters with fewer faces than this are treated as noise and not assigned to a person. "
            "Increase to reduce false clusters from accidental detections. Default: 2.",
            self._min_size_combo,
        )

        v.addWidget(thresh_group)

        # ── Reset button ───────────────────────────────────────────────
        from memoria.ui.fluent_icons import fi, FONT_NAME
        reset_btn = QPushButton(f"{fi.REFRESH}  Reset to defaults")
        reset_btn.setFont(QFont(FONT_NAME, 11))
        reset_btn.setFixedHeight(30)
        reset_btn.setStyleSheet(
            "QPushButton { background:#3a3a3a; color:#d4d4d4; border:1px solid #555; "
            "border-radius:4px; padding:2px 12px; }"
            "QPushButton:hover { background:#4a4a4a; }"
        )
        reset_btn.clicked.connect(self._reset_defaults)
        reset_row = QHBoxLayout()
        reset_row.addStretch()
        reset_row.addWidget(reset_btn)
        v.addLayout(reset_row)

        v.addStretch()

    def _on_provider_changed(self, _):
        cur_model = self._caption_model_combo.currentData()
        self._refresh_caption_models(cur_model)

    def _refresh_caption_models(self, current: str = ""):
        from memoria.ai.caption import GEMINI_MODELS
        provider = self._provider_combo.currentData() if hasattr(self, "_provider_combo") else "gemini"
        models = GEMINI_MODELS if provider == "gemini" else []
        self._caption_model_combo.blockSignals(True)
        self._caption_model_combo.clear()
        for m in models:
            self._caption_model_combo.addItem(m, m)
        idx = self._caption_model_combo.findData(current)
        self._caption_model_combo.setCurrentIndex(max(0, idx))
        self._caption_model_combo.blockSignals(False)

    def _float_slider_widget(self, slider: QSlider) -> QWidget:
        """Slider with value label above, formatted as 0.00."""
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        lbl = QLabel(f"{slider.value() / 100:.2f}")
        lbl.setStyleSheet("color:#d4d4d4; font-size:12px; background:transparent;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        slider.valueChanged.connect(lambda v, l=lbl: l.setText(f"{v / 100:.2f}"))
        col.addWidget(lbl)
        col.addWidget(slider)
        return w

    def _reset_defaults(self):
        self._model_combo.setCurrentIndex(
            max(0, self._model_combo.findText(self._DEFAULTS["face_model"])))
        self._detector_combo.setCurrentIndex(
            max(0, self._detector_combo.findText(self._DEFAULTS["detector_backend"])))
        self._match_slider.setValue(int(self._DEFAULTS["match_threshold"] * 100))
        self._cluster_slider.setValue(int(self._DEFAULTS["cluster_threshold"] * 100))
        self._min_size_combo.setCurrentIndex(int(self._DEFAULTS["min_cluster_size"]) - 1)

    def apply(self, settings: dict):
        settings["ai_provider"] = self._provider_combo.currentData()
        # API key + model stored in DB (never in settings JSON / git)
        from memoria.database.db import set_app_setting
        set_app_setting("ai_api_key",       self._api_key_input.text().strip())
        set_app_setting("ai_caption_model", self._caption_model_combo.currentData() or "gemini-2.0-flash-lite")
        settings["face_model"]        = self._model_combo.currentText()
        settings["detector_backend"]  = self._detector_combo.currentText()
        settings["match_threshold"]   = round(self._match_slider.value() / 100, 2)
        settings["cluster_threshold"] = round(self._cluster_slider.value() / 100, 2)
        settings["min_cluster_size"]  = self._min_size_combo.currentData()


class _HotkeysPage(QWidget):
    _SHORTCUTS = [
        ("Ctrl+R",        "Re-index folders",
         "Scan watched folders for new or changed photos and videos."),
        ("Ctrl+F",        "Name faces",
         "Open the face cluster naming dialog."),
        ("Ctrl+P",        "People",
         "Browse and manage named people and their face assignments."),
        ("Ctrl+B",        "Bulk edit",
         "Edit title, subject, location and tags for all currently displayed photos."),
        ("Ctrl+Shift+R",  "Re-assess",
         "Scan unprocessed photos, match faces to known people, and sync tags."),
        ("Ctrl+D",        "Review duplicates",
         "Step through detected duplicate pairs and keep or trash one."),
        ("Ctrl+,",        "Options",
         "Open this settings dialog."),
        ("Ctrl+Q",        "Quit",
         "Exit Memoria."),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        page, v = _page_layout()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(page)

        v.addWidget(_section_header("Keyboard Shortcuts"))

        group = _SettingGroup()
        for key, name, desc in self._SHORTCUTS:
            badge = QLabel(key)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedHeight(24)
            badge.setMinimumWidth(120)
            badge.setStyleSheet(
                "background:#2a2a2a; color:#d4d4d4; font-family:monospace; "
                "font-size:11px; border:1px solid #444; border-radius:3px; "
                "padding:0 8px;"
            )
            group.add_row(name, desc, badge)

        v.addWidget(group)
        v.addStretch()

        note = QLabel("Keyboard shortcuts are not currently customisable.")
        note.setStyleSheet("color:#555; font-size:10px;")
        v.addWidget(note)


# ── Library page ─────────────────────────────────────────────────────────────

class _LibraryPage(QWidget):
    """Options page for managing watched folder locations."""

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: #1e1e1e; }")
        outer.addWidget(scroll)

        page, v = _page_layout()
        scroll.setWidget(page)

        # ── Top heading — matches General / Editor / etc. ─────────────────
        v.addWidget(_section_header("Library"))

        # ── Watched Folders card — same grey card as other groups ─────────
        card = _SettingGroup()
        card._layout.setContentsMargins(16, 12, 16, 12)
        card._layout.setSpacing(8)

        title_lbl = QLabel("Watched Folders")
        title_lbl.setStyleSheet(_TITLE_CSS)
        card._layout.addWidget(title_lbl)

        desc_lbl = QLabel(
            "Memoria scans these folders for photos and videos. "
            "Changes take effect the next time you re-index (File → Re-index folders)."
        )
        desc_lbl.setStyleSheet(_DESC_CSS)
        desc_lbl.setWordWrap(True)
        card._layout.addWidget(desc_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#333; border:none;")
        card._layout.addWidget(sep)

        # Folder list — transparent bg so the card bg shows through
        self._folder_list = QListWidget()
        self._folder_list.setMinimumHeight(140)
        self._folder_list.setStyleSheet("""
            QListWidget {
                background: #2d2d2d;
                border: none;
                border-radius: 4px;
                font-size: 12px;
                color: #d4d4d4;
                outline: none;
                padding: 4px 0;
            }
            QListWidget::item { padding: 5px 10px; }
            QListWidget::item:selected { background: #37373d; color: #fff; }
            QListWidget::item:hover:!selected { background: #333333; }
        """)
        self._load_folders()
        card._layout.addWidget(self._folder_list)

        # Buttons row — directly below the list
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.setContentsMargins(0, 4, 0, 0)

        add_btn = QPushButton("+ Add Folder…")
        add_btn.setFixedHeight(28)
        add_btn.clicked.connect(self._add_folder)
        btn_row.addWidget(add_btn)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.setFixedHeight(28)
        remove_btn.setStyleSheet(
            "QPushButton { background:#3a2020; color:#f38ba8; border:1px solid #5a3030; "
            "border-radius:4px; padding:2px 10px; }"
            "QPushButton:hover { background:#5a2020; }"
        )
        remove_btn.clicked.connect(self._remove_folder)
        btn_row.addWidget(remove_btn)

        btn_row.addStretch()
        card._layout.addLayout(btn_row)

        v.addWidget(card)
        v.addStretch()

    def _load_folders(self):
        self._folder_list.clear()
        try:
            from memoria.database.db import get_session
            from memoria.database.models import WatchedFolder
            session = get_session()
            folders = session.query(WatchedFolder).order_by(WatchedFolder.path).all()
            session.close()
            for f in folders:
                self._folder_list.addItem(f.path)
        except Exception as e:
            pass

    def _add_folder(self):
        from PyQt6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "Select folder to watch")
        if not folder:
            return
        try:
            from memoria.database.db import get_session
            from memoria.database.models import WatchedFolder
            session = get_session()
            existing = session.query(WatchedFolder).filter_by(path=folder).first()
            if existing is None:
                session.add(WatchedFolder(path=folder))
                session.commit()
                self._folder_list.addItem(folder)
            session.close()
        except Exception as e:
            pass

    def _remove_folder(self):
        row = self._folder_list.currentRow()
        if row < 0:
            return
        path = self._folder_list.item(row).text()
        reply = QMessageBox.question(
            self, "Remove Folder",
            f"Remove \"{path}\" from the watch list?\n\n"
            "Photos already indexed will remain in the library.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            from memoria.database.db import get_session
            from memoria.database.models import WatchedFolder
            session = get_session()
            session.query(WatchedFolder).filter_by(path=path).delete()
            session.commit()
            session.close()
            self._folder_list.takeItem(row)
        except Exception as e:
            pass

    def apply(self, settings: dict):
        pass  # All changes are written to the DB immediately


# ── Status / Completion Criteria page ────────────────────────────────────────

class _StatusPage(QWidget):
    """
    Options page — configure which fields must be filled for a photo to be
    considered 'complete'.  Changes are saved to AppSetting immediately.
    """

    _CHK_CSS = """
        QCheckBox { color:#d4d4d4; font-size:12px; spacing:8px; }
        QCheckBox::indicator {
            width:14px; height:14px; border-radius:3px;
            border:1px solid #555; background:#2a2a2a;
        }
        QCheckBox::indicator:checked {
            background:#7c6af7; border-color:#7c6af7;
        }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._criteria: dict = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;background:#1e1e1e;}")
        outer.addWidget(scroll)

        page, v = _page_layout()
        scroll.setWidget(page)

        v.addWidget(_section_header("Completion Criteria"))

        # ── Criteria card ────────────────────────────────────────────────────
        card = _SettingGroup()
        card._layout.setContentsMargins(16, 12, 16, 12)
        card._layout.setSpacing(6)

        title_lbl = QLabel("Required fields")
        title_lbl.setStyleSheet(_TITLE_CSS)
        card._layout.addWidget(title_lbl)

        desc_lbl = QLabel(
            "Tick each field that must be completed for a photo to be considered "
            "fully catalogued.  The grid overlay and status indicators update in real-time."
        )
        desc_lbl.setStyleSheet(_DESC_CSS)
        desc_lbl.setWordWrap(True)
        card._layout.addWidget(desc_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#333;border:none;")
        card._layout.addWidget(sep)

        from memoria.file_status import DEFAULT_CRITERIA, FIELD_LABELS, get_criteria
        self._criteria = get_criteria()

        self._checks: dict[str, QCheckBox] = {}
        for key, label in FIELD_LABELS.items():
            row = QWidget()
            row.setStyleSheet("background:transparent;")
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(0)
            chk = QCheckBox(label)
            chk.setStyleSheet(self._CHK_CSS)
            chk.setChecked(bool(self._criteria.get(key, False)))
            chk.stateChanged.connect(self._on_change)
            self._checks[key] = chk
            h.addWidget(chk)

            # Min-tags spinner for the tags criterion
            if key == "require_tags":
                from PyQt6.QtWidgets import QSpinBox
                self._min_tags_spin = QSpinBox()
                self._min_tags_spin.setRange(1, 20)
                self._min_tags_spin.setValue(int(self._criteria.get("min_tags", 1)))
                self._min_tags_spin.setSuffix(" tag(s) minimum")
                self._min_tags_spin.setFixedWidth(160)
                self._min_tags_spin.setStyleSheet(
                    "QSpinBox{background:#3a3a3a;border:1px solid #555;"
                    "border-radius:4px;color:#d4d4d4;padding:2px 6px;font-size:11px;}"
                )
                self._min_tags_spin.setEnabled(chk.isChecked())
                chk.stateChanged.connect(
                    lambda s, sp=self._min_tags_spin: sp.setEnabled(bool(s))
                )
                self._min_tags_spin.valueChanged.connect(self._on_change)
                h.addSpacing(16)
                h.addWidget(self._min_tags_spin)

            h.addStretch()
            card._layout.addWidget(row)

        v.addWidget(card)

        # ── Library summary card ─────────────────────────────────────────────
        summary_card = _SettingGroup()
        summary_card._layout.setContentsMargins(16, 12, 16, 12)
        summary_card._layout.setSpacing(6)

        summary_title = QLabel("Library completion")
        summary_title.setStyleSheet(_TITLE_CSS)
        summary_card._layout.addWidget(summary_title)

        self._summary_lbl = QLabel("Click Refresh to calculate…")
        self._summary_lbl.setStyleSheet(_DESC_CSS)
        summary_card._layout.addWidget(self._summary_lbl)

        refresh_btn = QPushButton("↺  Refresh stats")
        refresh_btn.setFixedHeight(26)
        refresh_btn.setStyleSheet(
            "QPushButton{background:#3a3a3a;color:#d4d4d4;border:1px solid #555;"
            "border-radius:4px;padding:2px 12px;font-size:12px;}"
            "QPushButton:hover{background:#4a4a4a;}"
        )
        refresh_btn.clicked.connect(self._refresh_stats)
        summary_card._layout.addWidget(refresh_btn)

        v.addWidget(summary_card)
        v.addStretch()

    def _on_change(self):
        """Write updated criteria to DB immediately."""
        from memoria.file_status import set_criteria
        c = dict(self._criteria)
        for key, chk in self._checks.items():
            c[key] = chk.isChecked()
        c["min_tags"] = self._min_tags_spin.value()
        self._criteria = c
        set_criteria(c)

    def _refresh_stats(self):
        try:
            from memoria.database.db import get_session
            from memoria.file_status import count_library_completion
            session = get_session()
            complete, intentional, total = count_library_completion(
                session, self._criteria
            )
            session.close()
            done = complete + intentional
            pct  = round(done / total * 100) if total else 0
            self._summary_lbl.setText(
                f"<b>{complete}</b> complete,  "
                f"<b>{intentional}</b> intentionally incomplete,  "
                f"<b>{total - done}</b> still need work  "
                f"— {pct}% of {total:,} photos"
            )
        except Exception as e:
            self._summary_lbl.setText(f"Error: {e}")

    def apply(self, settings: dict):
        pass   # criteria written to DB on every change


# ── Locations page ────────────────────────────────────────────────────────────

class _LocationsPage(QWidget):
    """
    Options page — manage location labels stored against photos.

    Shows every distinct location currently in the library with a photo count.
    Operations: Rename (updates all photos using that label), Delete (clears the
    label from all photos), and Merge (fold one label into another).
    """

    _TABLE_CSS = """
        QTableWidget {
            background:#2d2d2d; border:1px solid #3a3a3a;
            border-radius:4px; font-size:12px; color:#d4d4d4;
            gridline-color:#333; outline:none;
        }
        QTableWidget::item { padding:4px 10px; border:none; }
        QTableWidget::item:selected { background:#3e3e6a; color:#fff; }
        QHeaderView::section {
            background:#252526; color:#777; font-size:10px; font-weight:600;
            border:none; border-bottom:1px solid #3a3a3a; padding:3px 10px;
        }
        QScrollBar:vertical {
            background:#252526; width:8px; border-radius:4px;
        }
        QScrollBar::handle:vertical { background:#555; border-radius:4px; }
    """
    _BTN_CSS = (
        "QPushButton{background:#3a3a3a;color:#d4d4d4;border:1px solid #555;"
        "border-radius:4px;padding:4px 14px;font-size:12px;}"
        "QPushButton:hover{background:#4a4a4a;}"
        "QPushButton:disabled{color:#555;border-color:#333;}"
    )
    _DEL_BTN_CSS = (
        "QPushButton{background:#3a2020;color:#f38ba8;border:1px solid #5a3030;"
        "border-radius:4px;padding:4px 14px;font-size:12px;}"
        "QPushButton:hover{background:#5a2020;}"
        "QPushButton:disabled{color:#555;border-color:#333;}"
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;background:#1e1e1e;}")
        outer.addWidget(scroll)

        page, v = _page_layout()
        scroll.setWidget(page)

        v.addWidget(_section_header("Locations"))

        # ── Card ─────────────────────────────────────────────────────────────
        card = _SettingGroup()
        card._layout.setContentsMargins(16, 12, 16, 12)
        card._layout.setSpacing(8)

        title_lbl = QLabel("Location Labels")
        title_lbl.setStyleSheet(_TITLE_CSS)
        card._layout.addWidget(title_lbl)

        desc_lbl = QLabel(
            "All location labels assigned to photos in your library. "
            "Select one to rename it across all photos, merge it into another label, "
            "or clear it entirely."
        )
        desc_lbl.setStyleSheet(_DESC_CSS)
        desc_lbl.setWordWrap(True)
        card._layout.addWidget(desc_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#333;border:none;")
        card._layout.addWidget(sep)

        # Table
        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Location label", "Photos"])
        self._table.setStyleSheet(self._TABLE_CSS)
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._table.verticalHeader().hide()
        self._table.setShowGrid(False)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Fixed
        )
        self._table.setColumnWidth(1, 72)
        self._table.setMinimumHeight(180)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        card._layout.addWidget(self._table)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.setContentsMargins(0, 4, 0, 0)

        self._rename_btn = QPushButton("✏  Rename…")
        self._rename_btn.setFixedHeight(28)
        self._rename_btn.setStyleSheet(self._BTN_CSS)
        self._rename_btn.setEnabled(False)
        self._rename_btn.clicked.connect(self._rename_location)
        btn_row.addWidget(self._rename_btn)

        self._merge_btn = QPushButton("⇒  Merge into…")
        self._merge_btn.setFixedHeight(28)
        self._merge_btn.setStyleSheet(self._BTN_CSS)
        self._merge_btn.setEnabled(False)
        self._merge_btn.clicked.connect(self._merge_location)
        btn_row.addWidget(self._merge_btn)

        self._delete_btn = QPushButton("✕  Clear from photos")
        self._delete_btn.setFixedHeight(28)
        self._delete_btn.setStyleSheet(self._DEL_BTN_CSS)
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._delete_location)
        btn_row.addWidget(self._delete_btn)

        btn_row.addStretch()

        refresh_btn = QPushButton("↺")
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setToolTip("Refresh list")
        refresh_btn.setStyleSheet(self._BTN_CSS)
        refresh_btn.clicked.connect(self._load)
        btn_row.addWidget(refresh_btn)

        card._layout.addLayout(btn_row)

        # Status label
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color:#777;font-size:11px;")
        card._layout.addWidget(self._status_lbl)

        v.addWidget(card)
        v.addStretch()

        self._load()

    # ── Data ─────────────────────────────────────────────────────────────────

    def _load(self):
        self._table.setRowCount(0)
        try:
            from memoria.database.db import get_session
            from memoria.database.models import Metadata
            from sqlalchemy import func
            session = get_session()
            rows = (
                session.query(
                    Metadata.location_label,
                    func.count(Metadata.file_id).label("n"),
                )
                .filter(
                    Metadata.location_label.isnot(None),
                    Metadata.location_label != "",
                )
                .group_by(Metadata.location_label)
                .order_by(Metadata.location_label)
                .all()
            )
            session.close()
        except Exception as e:
            self._status_lbl.setText(f"Error loading locations: {e}")
            return

        for label, count in rows:
            r = self._table.rowCount()
            self._table.insertRow(r)
            lbl_item = QTableWidgetItem(label)
            cnt_item = QTableWidgetItem(str(count))
            cnt_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            self._table.setItem(r, 0, lbl_item)
            self._table.setItem(r, 1, cnt_item)

        n = self._table.rowCount()
        self._status_lbl.setText(
            f"{n} location{'s' if n != 1 else ''} in library."
        )
        self._on_selection_changed()

    def _selected_label(self) -> str | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        return item.text() if item else None

    def _on_selection_changed(self):
        sel = self._selected_label() is not None
        self._rename_btn.setEnabled(sel)
        self._merge_btn.setEnabled(sel)
        self._delete_btn.setEnabled(sel)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _rename_location(self):
        old = self._selected_label()
        if not old:
            return
        text, ok = _input_dialog(
            self, "Rename Location",
            f'Rename "{old}" to:',
            old,
        )
        if not ok or not text.strip() or text.strip() == old:
            return
        new = text.strip()
        try:
            from memoria.database.db import get_session
            from memoria.database.models import Metadata
            session = get_session()
            updated = (
                session.query(Metadata)
                .filter_by(location_label=old)
                .all()
            )
            for m in updated:
                m.location_label = new
            session.commit()
            session.close()
            count = len(updated)
            self._status_lbl.setText(
                f'Renamed "{old}" → "{new}" on {count} photo{"s" if count != 1 else ""}.'
            )
            self._load()
        except Exception as e:
            self._status_lbl.setText(f"Error: {e}")

    def _merge_location(self):
        old = self._selected_label()
        if not old:
            return
        # Build list of other labels
        labels = []
        for r in range(self._table.rowCount()):
            item = self._table.item(r, 0)
            if item and item.text() != old:
                labels.append(item.text())

        if not labels:
            QMessageBox.information(
                self, "Merge", "No other locations to merge into."
            )
            return

        target, ok = _combo_dialog(
            self, "Merge Location",
            f'Merge "{old}" into which location?',
            labels,
        )
        if not ok or not target:
            return

        try:
            from memoria.database.db import get_session
            from memoria.database.models import Metadata
            session = get_session()
            updated = (
                session.query(Metadata)
                .filter_by(location_label=old)
                .all()
            )
            for m in updated:
                m.location_label = target
            session.commit()
            session.close()
            count = len(updated)
            self._status_lbl.setText(
                f'Merged "{old}" → "{target}" ({count} photo{"s" if count != 1 else ""} updated).'
            )
            self._load()
        except Exception as e:
            self._status_lbl.setText(f"Error: {e}")

    def _delete_location(self):
        old = self._selected_label()
        if not old:
            return
        row = self._table.currentRow()
        count_item = self._table.item(row, 1)
        count = int(count_item.text()) if count_item else "?"
        reply = QMessageBox.question(
            self,
            "Clear Location",
            f'Remove the label "{old}" from {count} photo{"s" if count != 1 else ""}?\n\n'
            f'The label will be cleared — photos are not deleted.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            from memoria.database.db import get_session
            from memoria.database.models import Metadata
            session = get_session()
            (
                session.query(Metadata)
                .filter_by(location_label=old)
                .update({"location_label": None},
                        synchronize_session="fetch")
            )
            session.commit()
            session.close()
            self._status_lbl.setText(
                f'Cleared "{old}" from {count} photo{"s" if count != 1 else ""}.'
            )
            self._load()
        except Exception as e:
            self._status_lbl.setText(f"Error: {e}")

    def apply(self, settings: dict):
        pass   # All changes written to DB immediately


# ── Small dialog helpers ──────────────────────────────────────────────────────

def _input_dialog(parent, title: str, label: str,
                  default: str = "") -> tuple[str, bool]:
    """Simple text-input dialog styled for the dark theme."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setFixedWidth(400)
    dlg.setStyleSheet(
        "QDialog{background:#1e1e1e;color:#d4d4d4;}"
        "QLabel{color:#d4d4d4;font-size:12px;}"
        "QLineEdit{background:#3a3a3a;border:1px solid #555;border-radius:4px;"
        "color:#d4d4d4;padding:4px 8px;font-size:12px;}"
        "QLineEdit:focus{border-color:#7c6af7;}"
        "QPushButton{background:#3a3a3a;color:#d4d4d4;border:1px solid #555;"
        "border-radius:4px;padding:4px 16px;font-size:12px;}"
        "QPushButton:hover{background:#4a4a4a;}"
        "QPushButton#ok{background:#7c6af7;border-color:#7c6af7;color:#fff;}"
        "QPushButton#ok:hover{background:#9480ff;}"
    )
    v = QVBoxLayout(dlg)
    v.setContentsMargins(16, 14, 16, 14)
    v.setSpacing(10)
    v.addWidget(QLabel(label))
    edit = QLineEdit(default)
    edit.selectAll()
    v.addWidget(edit)
    brow = QHBoxLayout()
    brow.addStretch()
    cancel = QPushButton("Cancel"); brow.addWidget(cancel)
    ok     = QPushButton("OK");     ok.setObjectName("ok"); brow.addWidget(ok)
    v.addLayout(brow)
    cancel.clicked.connect(dlg.reject)
    ok.clicked.connect(dlg.accept)
    edit.returnPressed.connect(dlg.accept)
    result = dlg.exec()
    return edit.text(), result == QDialog.DialogCode.Accepted


def _combo_dialog(parent, title: str, label: str,
                  items: list[str]) -> tuple[str, bool]:
    """Combo-select dialog styled for the dark theme."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setFixedWidth(400)
    dlg.setStyleSheet(
        "QDialog{background:#1e1e1e;color:#d4d4d4;}"
        "QLabel{color:#d4d4d4;font-size:12px;}"
        "QComboBox{background:#3a3a3a;border:1px solid #555;border-radius:4px;"
        "color:#d4d4d4;padding:4px 8px;font-size:12px;}"
        "QComboBox::drop-down{border:none;width:20px;}"
        "QComboBox QAbstractItemView{background:#2d2d2d;color:#d4d4d4;"
        "selection-background-color:#5a4fd4;border:1px solid #555;}"
        "QPushButton{background:#3a3a3a;color:#d4d4d4;border:1px solid #555;"
        "border-radius:4px;padding:4px 16px;font-size:12px;}"
        "QPushButton:hover{background:#4a4a4a;}"
        "QPushButton#ok{background:#7c6af7;border-color:#7c6af7;color:#fff;}"
        "QPushButton#ok:hover{background:#9480ff;}"
    )
    v = QVBoxLayout(dlg)
    v.setContentsMargins(16, 14, 16, 14)
    v.setSpacing(10)
    v.addWidget(QLabel(label))
    combo = QComboBox()
    for item in items:
        combo.addItem(item)
    v.addWidget(combo)
    brow = QHBoxLayout()
    brow.addStretch()
    cancel = QPushButton("Cancel"); brow.addWidget(cancel)
    ok     = QPushButton("OK");     ok.setObjectName("ok"); brow.addWidget(ok)
    v.addLayout(brow)
    cancel.clicked.connect(dlg.reject)
    ok.clicked.connect(dlg.accept)
    result = dlg.exec()
    return combo.currentText(), result == QDialog.DialogCode.Accepted


# ── Main dialog ───────────────────────────────────────────────────────────────

class OptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Options")
        self.resize(720, 520)
        self.setMinimumSize(600, 420)

        from memoria.ui.settings_store import load
        self._settings = load()

        # Global spinbox styling — no visible arrows, clean number-only appearance
        a = self._settings.get("accent_colour", "#7c6af7")
        self.setStyleSheet(f"""
            QSpinBox, QDoubleSpinBox {{
                background: #3a3a3a;
                border: 1px solid #555;
                border-radius: 4px;
                color: #d4d4d4;
                padding: 2px 8px;
            }}
            QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {a}; }}
            QSpinBox::up-button, QSpinBox::down-button,
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
                width: 0;
                height: 0;
                border: none;
                background: none;
            }}
        """)

        self._build_ui()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left section list ─────────────────────────────────────────────
        self._section_list = QListWidget()
        self._section_list.setFixedWidth(150)
        a = self._settings.get("accent_colour", "#7c6af7")
        self._section_list.setStyleSheet(f"""
            QListWidget {{
                background: #252526;
                border: none;
                border-right: 1px solid #333;
                outline: none;
                padding: 4px 0;
                font-size: 12px;
            }}
            QListWidget::item {{
                color: #d4d4d4;
                padding: 1px 12px;
                min-height: 20px;
                max-height: 20px;
            }}
            QListWidget::item:selected {{
                background: #37373d;
                color: #ffffff;
                border-left: 3px solid {a};
                padding-left: 9px;
            }}
            QListWidget::item:hover:!selected {{ background: #2d2d2d; }}
        """)
        self._section_list.setFrameShape(QListWidget.Shape.NoFrame)

        for name in ("General", "Editor", "Metadata", "Appearance", "Hotkeys", "Library", "Locations", "Status", "AI"):
            self._section_list.addItem(QListWidgetItem(name))
        self._section_list.setCurrentRow(0)
        self._section_list.currentRowChanged.connect(self._on_section_changed)
        root.addWidget(self._section_list)

        # ── Right stacked pages ───────────────────────────────────────────
        right = QWidget()
        right.setStyleSheet(f"background:{_PAGE_BG};")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(20, 20, 20, 16)
        right_layout.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background:transparent;")

        self._pages = [
            _GeneralPage(self._settings),
            _EditorPage(self._settings),
            _MetadataPage(),
            _AppearancePage(self._settings),
            _HotkeysPage(),
            _LibraryPage(),
            _LocationsPage(),
            _StatusPage(),
            _AIPage(self._settings),
        ]
        for page in self._pages:
            self._stack.addWidget(page)

        right_layout.addWidget(self._stack, stretch=1)
        right_layout.addSpacing(12)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Apply
        )
        btns.accepted.connect(self._save_and_close)
        btns.rejected.connect(self.reject)
        btns.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        right_layout.addWidget(btns)

        root.addWidget(right, stretch=1)

    def _on_section_changed(self, idx: int):
        self._stack.setCurrentIndex(idx)

    def _apply(self):
        from memoria.ui.settings_store import save
        for page in self._pages:
            if hasattr(page, "apply"):
                page.apply(self._settings)
        save(self._settings)

    def _save_and_close(self):
        self._apply()
        self.accept()
