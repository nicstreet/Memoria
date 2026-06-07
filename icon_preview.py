# Segoe icon preview - icons needed for Memoria
import sys
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

app = QApplication(sys.argv)

win = QWidget()
win.setWindowTitle("Segoe icons for Memoria")
win.setStyleSheet("background:#1e1e1e; color:#d4d4d4;")
win.resize(720, 680)

scroll = QScrollArea(win)
scroll.setWidgetResizable(True)
scroll.setStyleSheet("QScrollArea{border:none;background:#1e1e1e;}")
scroll.resize(720, 680)

container = QWidget()
container.setStyleSheet("background:#1e1e1e;")
root = QHBoxLayout(container)
root.setContentsMargins(12, 12, 12, 12)
root.setSpacing(12)
scroll.setWidget(container)

# (label, Fluent codepoint, MDL2 codepoint)
ICONS = [
    ("Sidebar toggle",    "", ""),  # GlobalNavButton
    ("Sidebar panel",     "", ""),  # SidePanel / SidePanelMirrored
    ("Panel left",        "", ""),  # PanelLeft (Fluent only)
    ("Rotate CW",         "", ""),  # RotateCamera
    ("Rotate (alt)",      "", ""),  # Rotate arrows
    ("Person / Face",     "", ""),  # People
    ("Contact",           "", ""),  # Contact (single person)
    ("Face scan",         "", ""),  # FaceRetouchExtended
    ("Not duplicate",     "", ""),  # Copy
    ("Cancel / X",        "", ""),  # Cancel
    ("Tag",               "", ""),  # Tag
    ("Settings",          "", ""),  # Settings
    ("Search",            "", ""),  # Search
    ("Bulk edit",         "", ""),  # Edit
    ("Multi select",      "", ""),  # SelectAll
    ("Refresh",           "", ""),  # Refresh
    ("Delete",            "", ""),  # Delete
    ("Rename",            "", ""),  # Rename
    ("CheckMark",         "", ""),  # Accept
    ("Add",               "", ""),  # Add
    ("Photo",             "", ""),  # Photo
    ("Library",           "", ""),  # Library
    ("Duplicate",         "", ""),  # Copy / CopyTo
    ("Options",           "", ""),  # Settings gear
]


def col_card(title: str, font_name: str, idx: int):
    w = QWidget()
    w.setStyleSheet("background:#252526; border-radius:8px;")
    v = QVBoxLayout(w)
    v.setContentsMargins(14, 12, 14, 14)
    v.setSpacing(4)

    hdr = QLabel(title)
    hdr.setStyleSheet("color:#aaa; font-size:11px; font-weight:600; background:transparent;")
    v.addWidget(hdr)

    sep = QWidget()
    sep.setFixedHeight(1)
    sep.setStyleSheet("background:#3a3a3a;")
    v.addWidget(sep)

    f = QFont(font_name, 18)

    for label, fluent_cp, mdl2_cp in ICONS:
        glyph = fluent_cp if idx == 0 else mdl2_cp
        row = QWidget()
        row.setStyleSheet("background:transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 1, 0, 1)
        h.setSpacing(8)

        g = QLabel(glyph)
        g.setFont(f)
        g.setFixedWidth(32)
        g.setAlignment(Qt.AlignmentFlag.AlignCenter)
        g.setStyleSheet("color:#d4d4d4; background:transparent;")
        h.addWidget(g)

        lbl = QLabel(label)
        lbl.setStyleSheet("color:#c0c0c0; font-size:11px; background:transparent;")
        h.addWidget(lbl, stretch=1)

        cp_lbl = QLabel(f"U+{ord(glyph):04X}")
        cp_lbl.setStyleSheet("color:#555; font-size:9px; background:transparent;")
        cp_lbl.setFixedWidth(48)
        h.addWidget(cp_lbl)

        v.addWidget(row)

    v.addStretch()
    return w


root.addWidget(col_card("Segoe Fluent Icons  (Win 11)", "Segoe Fluent Icons", 0))
root.addWidget(col_card("Segoe MDL2 Assets  (Win 10/11)", "Segoe MDL2 Assets", 1))

win.show()
sys.exit(app.exec())
