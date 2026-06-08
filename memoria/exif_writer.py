"""
EXIF tag writer — uses exiftool to sync Memoria tags to image files.

Writes to both:
  • IPTC:Keywords       — classic field, shown in Windows Explorer / Lightroom
  • XMP-dc:Subject      — modern XML field, used by newer apps

Only photos are written to; videos are skipped.
Runs non-destructively: exiftool writes a _original backup unless
-overwrite_original is passed (we do pass it — Memoria is the source
of truth and the DB already records the canonical state).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# Resolved once at import time; falls back to searching PATH
_EXIFTOOL_CANDIDATES = [
    r"C:\Users\stree\.tools\exiftool.exe",
    "exiftool",          # on PATH
    "exiftool.exe",
]

_SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".tif", ".tiff", ".png",
    ".heic", ".heif", ".webp", ".bmp",
}


def _exiftool_path() -> str | None:
    """Return a usable exiftool path, or None if not found."""
    for candidate in _EXIFTOOL_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
        if shutil.which(candidate):
            return candidate
    return None


def write_tags_to_file(filepath: str, tags: list[str]) -> bool:
    """
    Replace the IPTC Keywords and XMP Subject on *filepath* with *tags*.
    Passing an empty list clears all keywords.
    Returns True on success, False on failure (logged, never raises).
    """
    ext = Path(filepath).suffix.lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        log.debug(f"Skipping EXIF write for unsupported format: {filepath}")
        return False

    tool = _exiftool_path()
    if tool is None:
        log.warning("exiftool not found — tags will not be written to files")
        return False

    # Strip internal-only tags that should never appear in file metadata
    _INTERNAL_TAGS = {"unknown"}
    tags = [t for t in tags if t.lower() not in _INTERNAL_TAGS]

    # Build the argument list.
    # Clearing first (-Keywords= -Subject=) then setting ensures a clean replace
    # rather than appending to whatever was already in the file.
    args = [tool, "-overwrite_original", "-charset", "UTF8"]

    # Clear existing
    args += ["-IPTC:Keywords=", "-XMP-dc:Subject="]

    # Set new values (one flag per tag)
    for tag in tags:
        args += [f"-IPTC:Keywords={tag}", f"-XMP-dc:Subject={tag}"]

    args.append(filepath)

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            log.warning(
                f"exiftool returned {result.returncode} for {filepath}: "
                f"{result.stderr.strip()}"
            )
            return False
        log.debug(f"Tags written to {Path(filepath).name}: {tags}")
        return True
    except subprocess.TimeoutExpired:
        log.warning(f"exiftool timed out writing tags to {filepath}")
        return False
    except Exception as e:
        log.warning(f"exiftool error writing tags to {filepath}: {e}")
        return False


def sync_all_tags(session, progress=None) -> dict:
    """
    Write every file's current Memoria tags to its IPTC/XMP metadata.
    Called during re-assess step 4 to catch anything missed.
    Returns {"files_written": N, "files_skipped": N, "errors": N}.
    """
    from memoria.database.models import File, FileTag, Tag
    from sqlalchemy import func

    tool = _exiftool_path()
    if tool is None:
        log.warning("exiftool not found — skipping EXIF sync")
        return {"files_written": 0, "files_skipped": 0, "errors": 0}

    # Fetch all photos with their tags in one query
    photos = (
        session.query(File)
        .filter(File.file_type == "photo")
        .all()
    )

    written = skipped = errors = 0
    total = len(photos)

    for i, photo in enumerate(photos):
        if progress:
            progress(i + 1, total, f"Syncing tags to files ({i + 1}/{total})…")

        tag_rows = (
            session.query(Tag.label)
            .join(FileTag, FileTag.tag_id == Tag.id)
            .filter(FileTag.file_id == photo.id)
            .order_by(Tag.label)
            .all()
        )
        tags = [r.label for r in tag_rows]

        if not Path(photo.filepath).exists():
            skipped += 1
            continue

        ok = write_tags_to_file(photo.filepath, tags)
        if ok:
            written += 1
        else:
            errors += 1

    log.info(f"EXIF sync complete: {written} written, {skipped} skipped, {errors} errors")
    return {"files_written": written, "files_skipped": skipped, "errors": errors}
