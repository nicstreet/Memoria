"""
Theme singleton — holds the current accent colour and notifies the app
when it changes so the global stylesheet can be regenerated.
"""
from __future__ import annotations

_accent: str = "#7c6af7"


def accent() -> str:
    return _accent


def accent_hover() -> str:
    """Slightly lighter variant used for hover states."""
    return _lighten(_accent, 0.15)


def accent_dim() -> str:
    """Muted variant used for selection backgrounds."""
    return _darken(_accent, 0.15)


def set_accent(colour: str):
    global _accent
    _accent = colour
    _apply_to_app()


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _lighten(h: str, amount: float) -> str:
    r, g, b = _hex_to_rgb(h)
    r = min(255, int(r + (255 - r) * amount))
    g = min(255, int(g + (255 - g) * amount))
    b = min(255, int(b + (255 - b) * amount))
    return _rgb_to_hex(r, g, b)


def _darken(h: str, amount: float) -> str:
    r, g, b = _hex_to_rgb(h)
    r = max(0, int(r * (1 - amount)))
    g = max(0, int(g * (1 - amount)))
    b = max(0, int(b * (1 - amount)))
    return _rgb_to_hex(r, g, b)


def _apply_to_app():
    """Re-apply the global stylesheet with the new accent colour."""
    try:
        from PyQt6.QtWidgets import QApplication
        from memoria.ui.styles import get_dark_style
        app = QApplication.instance()
        if app:
            app.setStyleSheet(get_dark_style())
    except Exception:
        pass
