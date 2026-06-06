"""
Generates small UI icon PNG files on first run and returns their paths.
Uses Pillow (already a dependency) — no external image files needed.
"""
from pathlib import Path
from memoria.config import APPDATA_DIR

ICONS_DIR = APPDATA_DIR / "icons"
ICONS_DIR.mkdir(exist_ok=True)


def _make_arrow(path: Path, size: int = 48, color=(170, 170, 170)):
    """Draw a downward-pointing triangle and save as PNG."""
    if path.exists():
        return
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = size // 4
    mid = size // 2
    draw.polygon(
        [(pad, pad), (size - pad, pad), (mid, size - pad)],
        fill=(*color, 255),
    )
    img.save(str(path))


def arrow_down_path() -> str:
    path = ICONS_DIR / "arrow_down.png"
    _make_arrow(path)
    # Qt needs forward slashes on Windows
    return str(path).replace("\\", "/")
