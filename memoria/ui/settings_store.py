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
    "columns": 5,
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
