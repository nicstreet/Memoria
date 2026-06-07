"""
File status — completeness scoring and auto-rename.

A photo earns one point for each satisfied condition:
  1. Title set
  2. Subject set
  3. Named face present (or no faces detected — N/A counts as satisfied)
  4. File renamed in YY-MM-DD_HH-MM_Subject format

When points 1–3 are all satisfied the file is renamed automatically
and point 4 is awarded.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# Chars not allowed in filenames
_UNSAFE = re.compile(r'[\\/:*?"<>|]')


def _safe(text: str) -> str:
    """Sanitise a string for use as a filename component."""
    return _UNSAFE.sub("_", text).strip()[:60]


# ── Status computation ────────────────────────────────────────────────────────

def compute_status(file_id: int, session: Session) -> dict:
    """
    Return a status dict for one file:
      {
        "title":   str | None,
        "subject": str | None,
        "has_title":    bool,
        "has_subject":  bool,
        "face_ok":      bool,   # True = named face OR no faces at all
        "face_detail":  str,    # "named" | "unidentified" | "none"
        "renamed":      bool,
        "score":        int,    # 0–4
        "complete":     bool,
      }
    """
    from memoria.database.models import FaceDetection, File, Metadata

    file_row = session.query(File).get(file_id)
    meta_row = session.query(Metadata).filter_by(file_id=file_id).first()

    title   = (meta_row.title   or "").strip() if meta_row else ""
    subject = (meta_row.subject or "").strip() if meta_row else ""
    renamed = bool(file_row.renamed) if file_row else False

    has_title   = bool(title)
    has_subject = bool(subject)

    # Face condition
    detections = (
        session.query(FaceDetection)
        .filter(FaceDetection.file_id == file_id)
        .all()
    )
    if not detections:
        face_ok     = True          # no faces — condition N/A, counts as pass
        face_detail = "none"
    elif any(d.person_id is not None for d in detections):
        face_ok     = True
        face_detail = "named"
    else:
        face_ok     = False
        face_detail = "unidentified"

    score    = sum([has_title, has_subject, face_ok, renamed])
    complete = score == 4

    return {
        "title":        title or None,
        "subject":      subject or None,
        "has_title":    has_title,
        "has_subject":  has_subject,
        "face_ok":      face_ok,
        "face_detail":  face_detail,
        "renamed":      renamed,
        "score":        score,
        "complete":     complete,
    }


# ── Auto-rename ───────────────────────────────────────────────────────────────

def _target_filename(subject: str, date_taken: datetime | None,
                     suffix: str) -> str:
    """Build the canonical filename: YY-MM-DD_HH-MM_Subject.ext"""
    if date_taken:
        prefix = date_taken.strftime("%y-%m-%d_%H-%M")
    else:
        prefix = datetime.now().strftime("%y-%m-%d_%H-%M")
    return f"{prefix}_{_safe(subject)}{suffix}"


def maybe_auto_rename(file_id: int, session: Session) -> bool:
    """
    If points 1–3 are satisfied and the file hasn't been renamed yet,
    rename it and mark renamed=True.  Returns True if a rename occurred.
    """
    from memoria.database.models import File, Metadata

    status = compute_status(file_id, session)

    if status["renamed"]:
        return False                     # already done
    if not (status["has_title"] and status["has_subject"] and status["face_ok"]):
        return False                     # not all conditions met

    file_row = session.query(File).get(file_id)
    meta_row = session.query(Metadata).filter_by(file_id=file_id).first()
    if not file_row:
        return False

    old_path = Path(file_row.filepath)
    if not old_path.exists():
        log.warning(f"Cannot rename — file not found: {old_path}")
        return False

    date_taken = meta_row.date_taken if meta_row else None
    new_name   = _target_filename(status["subject"], date_taken, old_path.suffix)
    new_path   = old_path.parent / new_name

    # Avoid collisions
    if new_path.exists() and new_path != old_path:
        stem   = new_path.stem
        for i in range(1, 100):
            candidate = old_path.parent / f"{stem}_{i}{old_path.suffix}"
            if not candidate.exists():
                new_path = candidate
                break

    try:
        old_path.rename(new_path)
    except OSError as e:
        log.error(f"Rename failed {old_path} → {new_path}: {e}")
        return False

    # Update DB
    file_row.filepath = str(new_path)
    file_row.filename = new_path.name
    file_row.renamed  = True
    session.commit()

    log.info(f"Auto-renamed: {old_path.name} → {new_path.name}")
    return True
