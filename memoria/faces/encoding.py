import logging
import os
from pathlib import Path
from typing import Callable

import numpy as np
from sqlalchemy.orm import Session

from memoria.config import FACE_ENCODINGS_DIR, MODELS_DIR
from memoria.database.models import FaceDetection, File
from datetime import datetime

log = logging.getLogger(__name__)

# Tell DeepFace to store its downloaded models in our app data directory
os.environ.setdefault("DEEPFACE_HOME", str(MODELS_DIR))

MODEL_NAME = "ArcFace"          # fallback used before settings load
DETECTOR_BACKEND = "retinaface"  # fallback used before settings load


def _ai_settings() -> dict:
    """Load current AI settings at call-time so UI changes take effect immediately."""
    try:
        from memoria.ui.settings_store import load
        return load()
    except Exception:
        return {}


def _model_name() -> str:
    return _ai_settings().get("face_model", MODEL_NAME)


def _detector_backend() -> str:
    return _ai_settings().get("detector_backend", DETECTOR_BACKEND)

ProgressCallback = Callable[[int, int, str], None]


def _deepface_represent(img_path: str) -> list[dict]:
    """Lazy-import DeepFace and run face detection + embedding. Returns list of face dicts."""
    from deepface import DeepFace
    return DeepFace.represent(
        img_path=img_path,
        model_name=_model_name(),
        detector_backend=_detector_backend(),
        enforce_detection=True,
        align=True,
    )


def scan_faces_for_file(file_row: File, session: Session) -> int:
    """
    Detect and encode all faces in a single photo.
    Returns number of faces found. Never raises — logs errors and returns 0.
    """
    path = Path(file_row.filepath)

    try:
        results = _deepface_represent(str(path))
    except ValueError:
        # No face detected — normal, not an error
        file_row.face_scanned_at = datetime.utcnow()
        return 0
    except Exception as e:
        log.warning(f"Face detection failed for {path.name}: {e}")
        file_row.face_scanned_at = datetime.utcnow()
        return 0

    count = 0
    for i, face in enumerate(results):
        try:
            embedding = np.array(face["embedding"], dtype=np.float32)
            bbox = face.get("facial_area", {})
            confidence = face.get("face_confidence", None)

            # Save embedding to disk
            enc_filename = f"{file_row.id}_{i}.npy"
            enc_path = FACE_ENCODINGS_DIR / enc_filename
            np.save(str(enc_path), embedding)

            detection = FaceDetection(
                file_id=file_row.id,
                encoding_path=str(enc_path),
                bbox_x=bbox.get("x"),
                bbox_y=bbox.get("y"),
                bbox_w=bbox.get("w"),
                bbox_h=bbox.get("h"),
                face_confidence=confidence,
                person_id=None,
                cluster_id=None,
            )
            session.add(detection)
            count += 1
        except Exception as e:
            log.warning(f"Failed to store face {i} from {path.name}: {e}")

    file_row.face_scanned_at = datetime.utcnow()
    return count


def run_face_scan(
    session: Session,
    progress: ProgressCallback | None = None,
) -> dict:
    """
    Scan all unprocessed photos for faces.
    Resumable — skips files where face_scanned_at is already set.
    Returns stats dict.
    """
    def _progress(current: int, total: int, message: str):
        if progress:
            progress(current, total, message)
        else:
            log.info(f"[{current}/{total}] {message}")

    stats = {"scanned": 0, "faces_found": 0, "errors": 0}

    pending = (
        session.query(File)
        .filter(File.file_type == "photo", File.face_scanned_at.is_(None))
        .all()
    )
    total = len(pending)
    log.info(f"{total} photo(s) pending face scan")

    for i, file_row in enumerate(pending):
        _progress(i + 1, total, file_row.filename)
        try:
            faces = scan_faces_for_file(file_row, session)
            stats["faces_found"] += faces
            stats["scanned"] += 1
            session.commit()
        except Exception as e:
            session.rollback()
            stats["errors"] += 1
            log.error(f"Unexpected error scanning {file_row.filename}: {e}", exc_info=True)

    _progress(total, total, "Face scan complete")
    log.info(f"Face scan stats: {stats}")
    return stats
