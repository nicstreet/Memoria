"""
Segoe Fluent Icons helper (Windows 11 built-in font).
Falls back to Segoe MDL2 Assets on Windows 10.

Usage
-----
from memoria.ui.fluent_icons import fi, make_icon, FONT

# As text in a QLabel / QPushButton:
lbl.setFont(FONT)
lbl.setText(fi.ROTATE)

# As a QIcon (for QAction menus, toolbar buttons):
action.setIcon(make_icon(fi.SETTINGS))

# In QPainter (grid overlays):
painter.setFont(FONT)
painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, fi.ROTATE)
"""

from __future__ import annotations
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtCore import Qt, QRect

# ── Font selection ────────────────────────────────────────────────────────────

def _pick_font() -> str:
    from PyQt6.QtGui import QFontDatabase
    families = QFontDatabase.families()
    if "Segoe Fluent Icons" in families:
        return "Segoe Fluent Icons"
    return "Segoe MDL2 Assets"

FONT_NAME = _pick_font()
FONT      = QFont(FONT_NAME)


def font(size: int) -> QFont:
    return QFont(FONT_NAME, size)


# ── Codepoints ────────────────────────────────────────────────────────────────

class fi:
    """Fluent Icon glyph constants."""

    # Navigation / layout
    SIDEBAR         = ""   # GlobalNavButton  (hamburger / sidebar toggle)
    PANEL_LEFT      = ""   # PanelLeft        (left panel indicator)
    SIDE_PANEL      = ""   # SidePanel

    # Photo actions
    ROTATE          = ""   # RotateCamera
    ROTATE_ALT      = ""   # Rotate (circular arrows)
    PHOTO           = ""   # Photo
    CAMERA          = ""   # Camera

    # People / faces
    PERSON          = ""   # People
    CONTACT         = ""   # Contact (single person)
    FACE            = ""   # FaceRetouchExtended
    PEOPLE_ADD      = ""   # AddFriend

    # Files / tags
    TAG             = ""   # Tag
    COPY            = ""   # Copy
    COPY_X          = ""   # CopyTo (not-duplicate)
    DELETE          = ""   # Delete
    RENAME          = ""   # Rename
    EDIT            = ""   # Edit
    LIBRARY         = ""   # Library
    MULTI_SELECT    = ""   # SelectAll (bulk edit)
    FOLDER          = ""   # Folder

    # UI chrome
    SETTINGS        = ""   # Settings
    SEARCH          = ""   # Search
    REFRESH         = ""   # Refresh
    ADD             = ""   # Add
    CANCEL          = ""   # Cancel / X
    ACCEPT          = ""   # Accept / Checkmark
    FILTER          = ""   # Filter
    SORT            = ""   # Sort
    INFO            = ""   # Info
    HELP            = ""   # Help / question mark circle
    WARNING         = ""   # Warning
    SCAN            = ""   # Scan / Index


    # Extra location / date icons (explicit codepoints — robust across editors)
    CALENDAR  = ""   # Calendar
    MAP_PIN   = ""   # Map pin / location marker
    LOCATION  = ""   # Location
    GLOBE     = ""   # Globe

    # Window chrome — explicit codepoints for custom title bar
    CHROME_MINIMIZE = ""   # ChromeMinimize  (-)
    CHROME_MAXIMIZE = ""   # ChromeMaximize  (□)
    CHROME_RESTORE  = ""   # ChromeRestore   (❐)
    CHROME_CLOSE    = ""   # ChromeClose     (✕)


# ── QIcon factory ─────────────────────────────────────────────────────────────

def make_icon(glyph: str, size: int = 16,
              colour: str = "#d4d4d4") -> QIcon:
    """Render a Segoe glyph as a crisp HiDPI-aware QIcon.

    Creates the pixmap at the screen's physical pixel size and sets
    devicePixelRatio so Qt treats it as `size` logical pixels — no
    scaling step, so glyphs stay sharp at any DPI.
    """
    from PyQt6.QtWidgets import QApplication
    dpr = QApplication.primaryScreen().devicePixelRatio() if QApplication.instance() else 1.0
    phys = int(size * dpr)          # physical pixel dimensions

    px = QPixmap(phys, phys)
    px.setDevicePixelRatio(dpr)     # tell Qt: this is `size` logical px
    px.fill(Qt.GlobalColor.transparent)

    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    # Draw in logical coordinates (Qt maps to physical automatically)
    p.setFont(QFont(FONT_NAME, int(size * 0.7)))
    p.setPen(QColor(colour))
    p.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()
    return QIcon(px)
