"""
File status — configurable completeness scoring.

Criteria are stored in AppSetting["completion_criteria"] as JSON.
Each criterion is a boolean flag; some have extra parameters (e.g. min_tags).

Special tag: "[incomplete]" — written to EXIF, marks a photo as intentionally
incomplete.  Its presence turns the overlay amber and counts the photo as
"acknowledged" for workflow purposes.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

#: The tag label applied by "Mark as Intentionally Incomplete"
INTENTIONALLY_INCOMPLETE_TAG = "[incomplete]"

#: Default criteria — which fields count toward completion
DEFAULT_CRITERIA: dict = {
    "require_title":        True,
    "require_subject":      True,
    "require_location":     False,
    "require_tags":         False,
    "min_tags":             1,
    "require_faces":        True,
    "require_ai_confirmed": False,
    "require_filename":     True,
    "require_copyright":    False,
    "require_date":         False,
}

#: Human-readable names for each boolean criterion key
FIELD_LABELS: dict[str, str] = {
    "require_title":        "Title",
    "require_subject":      "Subject",
    "require_location":     "Location",
    "require_tags":         "Tags",
    "require_faces":        "Faces ID'd",
    "require_ai_confirmed": "AI Confirmed",
    "require_filename":     "Filename",
    "require_copyright":    "Copyright",
    "require_date":         "Date Taken",
}

#: Short label shown inside the grid overlay dots
FIELD_SHORT: dict[str, str] = {
    "require_title":        "T",
    "require_subject":      "S",
    "require_location":     "L",
    "require_tags":         "#",
    "require_faces":        "F",
    "require_ai_confirmed": "AI",
    "require_filename":     "N",
    "require_copyright":    "©",
    "require_date":         "D",
}

# Chars not allowed in filenames
_UNSAFE = re.compile(r'[\\/:*?"<>|]')


def _safe(text: str) -> str:
    return _UNSAFE.sub("_", text).strip()[:60]


# ── Criteria persistence ──────────────────────────────────────────────────────

def get_criteria() -> dict:
    """Load completion criteria from AppSetting (falls back to defaults)."""
    try:
        from memoria.database.db import get_app_setting
        raw = get_app_setting("completion_criteria", "")
        if raw:
            stored = json.loads(raw)
            return {**DEFAULT_CRITERIA, **stored}
    except Exception as e:
        log.warning(f"Could not load completion criteria: {e}")
    return dict(DEFAULT_CRITERIA)


def set_criteria(criteria: dict) -> None:
    """Persist completion criteria to AppSetting."""
    try:
        from memoria.database.db import set_app_setting
        set_app_setting("completion_criteria", json.dumps(criteria))
    except Exception as e:
        log.warning(f"Could not save completion criteria: {e}")


# ── Status computation ────────────────────────────────────────────────────────

def compute_status(file_id: int, session: Session,
                   criteria: dict | None = None) -> dict:
    """
    Return a comprehensive status dict for one file.

    Keys:
      fields          dict[str, bool]  — per-criterion pass/fail
      complete        bool             — all active criteria pass OR intentional
      intentional     bool             — has [incomplete] tag
      score           int              — criteria passing
      max_score       int              — total active criteria
      pct             float            — score / max_score (0.0–1.0)
      # legacy keys kept for backward compat
      has_title       bool
      has_subject     bool
      face_ok         bool
      face_detail     str
      renamed         bool
    """
    if criteria is None:
        criteria = get_criteria()

    from memoria.database.models import (
        EditLog, FaceDetection, File, FileTag, Metadata, Tag,
    )

    file_row = session.query(File).get(file_id)
    meta_row = session.query(Metadata).filter_by(file_id=file_id).first()

    title     = (meta_row.title     or "").strip() if meta_row else ""
    subject   = (meta_row.subject   or "").strip() if meta_row else ""
    location  = (meta_row.location_label or "").strip() if meta_row else ""
    copyright_ = (meta_row.copyright or "").strip() if meta_row else ""
    date_taken = meta_row.date_taken if meta_row else None
    renamed   = bool(file_row.renamed) if file_row else False

    # Tags
    tag_rows = (
        session.query(Tag.label)
        .join(FileTag, FileTag.tag_id == Tag.id)
        .filter(FileTag.file_id == file_id)
        .all()
    )
    tag_labels = [r.label for r in tag_rows]
    real_tags  = [t for t in tag_labels if t != INTENTIONALLY_INCOMPLETE_TAG]
    intentional = INTENTIONALLY_INCOMPLETE_TAG in tag_labels

    # Faces
    detections = (
        session.query(FaceDetection)
        .filter(FaceDetection.file_id == file_id).all()
    )
    if not detections:
        face_ok, face_detail = True, "none"
    elif any(d.person_id is not None for d in detections):
        face_ok, face_detail = True, "named"
    else:
        face_ok, face_detail = False, "unidentified"

    # AI confirmed — True if no pending AI entries (all confirmed or none exist)
    pending_ai = (
        session.query(EditLog)
        .filter(EditLog.file_id == file_id,
                EditLog.source == "ai",
                EditLog.ai_confirmed.is_(None))
        .count()
    )
    ai_confirmed = pending_ai == 0

    # Copyright (check EXIF Artist via metadata if we store it — fall back to False)
    has_copyright = bool(copyright_)

    # Per-field evaluation
    min_tags = max(1, int(criteria.get("min_tags", 1)))

    field_results: dict[str, bool] = {
        "require_title":        bool(title),
        "require_subject":      bool(subject),
        "require_location":     bool(location),
        "require_tags":         len(real_tags) >= min_tags,
        "require_faces":        face_ok,
        "require_ai_confirmed": ai_confirmed,
        "require_filename":     renamed,
        "require_copyright":    has_copyright,
        "require_date":         date_taken is not None,
    }

    # Only count enabled criteria
    active_keys = [k for k in FIELD_LABELS if criteria.get(k, False)]
    score     = sum(field_results[k] for k in active_keys)
    max_score = len(active_keys)
    pct       = score / max_score if max_score else 1.0
    complete  = (score == max_score) or intentional

    return {
        # New structured data
        "fields":       {k: field_results[k] for k in active_keys},
        "complete":     complete,
        "intentional":  intentional,
        "score":        score,
        "max_score":    max_score,
        "pct":          pct,
        # Legacy keys for backward compat
        "title":        title or None,
        "subject":      subject or None,
        "has_title":    bool(title),
        "has_subject":  bool(subject),
        "face_ok":      face_ok,
        "face_detail":  face_detail,
        "renamed":      renamed,
    }


def compute_status_batch(file_ids: list[int],
                          session: Session,
                          criteria: dict | None = None) -> dict[int, dict]:
    """
    Efficiently compute status for many files in 5 queries instead of 5×N.
    Returns {file_id: status_dict}.
    """
    if not file_ids:
        return {}
    if criteria is None:
        criteria = get_criteria()

    from memoria.database.models import (
        EditLog, FaceDetection, File, FileTag, Metadata, Tag,
    )

    # ── Bulk queries ──────────────────────────────────────────────────────────
    meta_map: dict[int, Metadata] = {}
    for m in session.query(Metadata).filter(Metadata.file_id.in_(file_ids)):
        meta_map[m.file_id] = m

    file_map: dict[int, File] = {}
    for f in session.query(File).filter(File.id.in_(file_ids)):
        file_map[f.id] = f

    # Faces: {file_id: [person_id|None, ...]}
    face_map: dict[int, list] = {fid: [] for fid in file_ids}
    for d in session.query(FaceDetection).filter(FaceDetection.file_id.in_(file_ids)):
        face_map[d.file_id].append(d.person_id)

    # Tags: {file_id: [label, ...]}
    tag_map: dict[int, list[str]] = {fid: [] for fid in file_ids}
    for row in (
        session.query(FileTag.file_id, Tag.label)
        .join(Tag, Tag.id == FileTag.tag_id)
        .filter(FileTag.file_id.in_(file_ids))
    ):
        tag_map[row.file_id].append(row.label)

    # Pending AI: set of file_ids that have unconfirmed AI entries
    pending_ai_ids: set[int] = set()
    for row in (
        session.query(EditLog.file_id)
        .filter(EditLog.file_id.in_(file_ids),
                EditLog.source == "ai",
                EditLog.ai_confirmed.is_(None))
        .distinct()
    ):
        pending_ai_ids.add(row.file_id)

    # ── Per-file computation ──────────────────────────────────────────────────
    min_tags  = max(1, int(criteria.get("min_tags", 1)))
    active_keys = [k for k in FIELD_LABELS if criteria.get(k, False)]

    results: dict[int, dict] = {}
    for fid in file_ids:
        m    = meta_map.get(fid)
        fr   = file_map.get(fid)
        tags = tag_map.get(fid, [])

        title    = (m.title    or "").strip() if m else ""
        subject  = (m.subject  or "").strip() if m else ""
        location = (m.location_label or "").strip() if m else ""
        copyright_ = (m.copyright or "").strip() if m else ""
        date_taken = m.date_taken if m else None
        renamed  = bool(fr.renamed) if fr else False

        real_tags  = [t for t in tags if t != INTENTIONALLY_INCOMPLETE_TAG]
        intentional = INTENTIONALLY_INCOMPLETE_TAG in tags

        face_list = face_map.get(fid, [])
        if not face_list:
            face_ok, face_detail = True, "none"
        elif any(p is not None for p in face_list):
            face_ok, face_detail = True, "named"
        else:
            face_ok, face_detail = False, "unidentified"

        ai_confirmed = fid not in pending_ai_ids

        field_results: dict[str, bool] = {
            "require_title":        bool(title),
            "require_subject":      bool(subject),
            "require_location":     bool(location),
            "require_tags":         len(real_tags) >= min_tags,
            "require_faces":        face_ok,
            "require_ai_confirmed": ai_confirmed,
            "require_filename":     renamed,
            "require_copyright":    bool(copyright_),
            "require_date":         date_taken is not None,
        }

        score    = sum(field_results[k] for k in active_keys)
        max_score = len(active_keys)
        pct      = score / max_score if max_score else 1.0
        complete = (score == max_score) or intentional

        results[fid] = {
            "fields":      {k: field_results[k] for k in active_keys},
            "complete":    complete,
            "intentional": intentional,
            "score":       score,
            "max_score":   max_score,
            "pct":         pct,
            # Legacy
            "has_title":   bool(title),
            "has_subject": bool(subject),
            "face_ok":     face_ok,
            "face_detail": face_detail,
            "renamed":     renamed,
        }

    return results


def count_library_completion(session: Session,
                              criteria: dict | None = None
                              ) -> tuple[int, int, int]:
    """
    Returns (complete, intentional, total) for the whole library.
    Only counts photos, not videos.
    """
    from memoria.database.models import File
    photo_ids = [
        r.id for r in
        session.query(File.id).filter(File.file_type == "photo").all()
    ]
    if not photo_ids:
        return 0, 0, 0

    if criteria is None:
        criteria = get_criteria()

    statuses = compute_status_batch(photo_ids, session, criteria)
    complete    = sum(1 for s in statuses.values() if s["complete"] and not s["intentional"])
    intentional = sum(1 for s in statuses.values() if s["intentional"])
    return complete, intentional, len(photo_ids)


# ── Auto-rename ───────────────────────────────────────────────────────────────

def _target_filename(subject: str, date_taken: datetime | None,
                     suffix: str) -> str:
    if date_taken:
        prefix = date_taken.strftime("%y-%m-%d_%H-%M")
    else:
        prefix = datetime.now().strftime("%y-%m-%d_%H-%M")
    return f"{prefix}_{_safe(subject)}{suffix}"


def maybe_auto_rename(file_id: int, session: Session) -> bool:
    """
    If title + subject + faces are all satisfied and file not yet renamed,
    rename it. Returns True if a rename occurred.
    """
    from memoria.database.models import File, Metadata

    st = compute_status(file_id, session)

    if st["renamed"]:
        return False
    if not (st["has_title"] and st["has_subject"] and st["face_ok"]):
        return False

    file_row = session.query(File).get(file_id)
    meta_row = session.query(Metadata).filter_by(file_id=file_id).first()
    if not file_row:
        return False

    old_path = Path(file_row.filepath)
    if not old_path.exists():
        log.warning(f"Cannot rename — file not found: {old_path}")
        return False

    date_taken = meta_row.date_taken if meta_row else None
    new_name   = _target_filename(st["subject"], date_taken, old_path.suffix)
    new_path   = old_path.parent / new_name

    if new_path.exists() and new_path != old_path:
        stem = new_path.stem
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

    file_row.filepath = str(new_path)
    file_row.filename = new_path.name
    file_row.renamed  = True
    session.commit()

    log.info(f"Auto-renamed: {old_path.name} → {new_path.name}")
    return True
