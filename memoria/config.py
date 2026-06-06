import os
from pathlib import Path

APP_NAME = "Memoria"

# All persistent data lives in %APPDATA%\Memoria\
APPDATA_DIR = Path(os.environ["APPDATA"]) / APP_NAME
DB_PATH = APPDATA_DIR / "memoria.db"
FACE_ENCODINGS_DIR = APPDATA_DIR / "face_encodings"
LOG_PATH = APPDATA_DIR / "memoria.log"
MODELS_DIR = APPDATA_DIR / "models"
THUMBNAILS_DIR = APPDATA_DIR / "thumbnails"

THUMBNAIL_SIZE = 200  # pixels (square)
CARD_WIDTH = 220
CARD_HEIGHT = 260

# Ensure directories exist on import
for _d in (APPDATA_DIR, FACE_ENCODINGS_DIR, MODELS_DIR, THUMBNAILS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
