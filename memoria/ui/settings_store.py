"""
Lightweight persistent settings using a JSON file in APPDATA.
Used for UI preferences that should survive restarts.
Full settings screen comes in Phase 4g.
"""
import json
import logging
from pathlib import Path

from memoria.config import APPDATA_DIR

SETTINGS_FILE = APPDATA_DIR / "ui_settings.json"

log = logging.getLogger(__name__)

_DEFAULTS = {
    # UI
    "columns":          5,
    "accent_colour":    "#7c6af7",
    "jpeg_quality":     100,
    "rename_format":    "%y-%m-%d_%H-%M_{subject}",
    "show_extensions":  True,
    # Editor behaviour
    "auto_write_exif":    False,
    # AI caption generation (api_key + model stored in DB, not here)
    "ai_provider":        "gemini",
    # AI / face detection
    "face_model":         "ArcFace",
    "detector_backend":   "retinaface",
    "match_threshold":    0.6,
    "cluster_threshold":  0.4,
    "min_cluster_size":   2,
}


def load() -> dict:
    try:
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return {**_DEFAULTS, **data}
    except Exception as e:
        log.warning(f"Could not load UI settings: {e}")
    return dict(_DEFAULTS)


def save(settings: dict):
    try:
        SETTINGS_FILE.write_text(
            json.dumps(settings, indent=2), encoding="utf-8"
        )
    except Exception as e:
        log.warning(f"Could not save UI settings: {e}")
