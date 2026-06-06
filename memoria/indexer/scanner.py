import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from memoria.database.models import Duplicate, File, Metadata, WatchedFolder
from memoria.indexer.exif import extract_photo_metadata, is_photo, PHOTO_EXTENSIONS
from memoria.indexer.video import extract_video_metadata, is_video, VIDEO_EXTENSIONS
from memoria.indexer.hashing import compute_phash, find_duplicates
from memoria.indexer.geocoder import reverse_geocode

log = logging.getLogger(__name__)

ALL_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

ProgressCallback = Callable[[int, int, str], None]  # (current, total, message)


def _collect_files(folders: list[str]) -> list[Path]:
    """Walk all watched folders and return every supported media file."""
    found = []
    for folder in folders:
        root = Path(folder)
        if not root.exists():
            log.warning(f"Watched folder not found, skipping: {folder}")
            continue
        for dirpath, _, filenames in os.walk(root):
            for fname in filenames:
                if Path(fname).suffix.lower() in ALL_EXTENSIONS:
                    found.append(Path(dirpath) / fname)
    return found


def _needs_indexing(path: Path, existing: File | None) -> bool:
    """True if the file has never been indexed or has been modified since last index."""
    if existing is None:
        return True
    try:
        mtime = datetime.utcfromtimestamp(path.stat().st_mtime)
        if existing.file_modified_at is None:
            return True
        # Allow 1-second tolerance for filesystem timestamp rounding
        return (mtime - existing.file_modified_at).total_seconds() > 1
    except OSError:
        return True


def run_index(
    session: Session,
    progress: ProgressCallback | None = None,
) -> dict:
    """
    Index all files from watched folders.
    Returns a stats dict: {scanned, added, updated, skipped, errors}.
    """
    def _progress(current: int, total: int, message: str):
        if progress:
            progress(current, total, message)
        else:
            log.info(f"[{current}/{total}] {message}")

    stats = {"scanned": 0, "added": 0, "updated": 0, "skipped": 0, "errors": 0}

    # Get watched folders
    folders = [wf.path for wf in session.query(WatchedFolder).all()]
    if not folders:
        log.warning("No watched folders configured. Add folders in Settings.")
        return stats

    _progress(0, 0, "Collecting files…")
    files = _collect_files(folders)
    total = len(files)
    log.info(f"Found {total} media files across {len(folders)} folder(s)")

    # Build lookup of already-indexed paths
    existing_map: dict[str, File] = {
        row.filepath: row for row in session.query(File).all()
    }

    for i, path in enumerate(files):
        stats["scanned"] += 1
        filepath_str = str(path)
        _progress(i + 1, total, path.name)

        existing = existing_map.get(filepath_str)

        if not _needs_indexing(path, existing):
            stats["skipped"] += 1
            continue

        try:
            stat = path.stat()
            file_type = "photo" if is_photo(path) else "video"

            # Upsert File row
            if existing is None:
                file_row = File(
                    filepath=filepath_str,
                    filename=path.name,
                    file_type=file_type,
                    size_bytes=stat.st_size,
                    file_modified_at=datetime.utcfromtimestamp(stat.st_mtime),
                    created_at=datetime.utcfromtimestamp(stat.st_ctime),
                    indexed_at=datetime.utcnow(),
                )
                session.add(file_row)
                session.flush()  # get file_row.id
                stats["added"] += 1
            else:
                existing.size_bytes = stat.st_size
                existing.file_modified_at = datetime.utcfromtimestamp(stat.st_mtime)
                existing.indexed_at = datetime.utcnow()
                file_row = existing
                stats["updated"] += 1

            # Extract metadata
            if file_type == "photo":
                meta_dict = extract_photo_metadata(path)
                phash = compute_phash(path)
            else:
                meta_dict = extract_video_metadata(path)
                phash = None  # phash not used for videos

            # Reverse geocode if GPS present
            location_label = None
            if meta_dict.get("gps_lat") is not None:
                location_label = reverse_geocode(meta_dict["gps_lat"], meta_dict["gps_lon"])

            # Upsert Metadata row
            meta_row = file_row.metadata_
            if meta_row is None:
                meta_row = Metadata(file_id=file_row.id)
                session.add(meta_row)

            meta_row.date_taken = meta_dict.get("date_taken")
            meta_row.gps_lat = meta_dict.get("gps_lat")
            meta_row.gps_lon = meta_dict.get("gps_lon")
            meta_row.location_label = location_label
            meta_row.camera_make = meta_dict.get("camera_make")
            meta_row.camera_model = meta_dict.get("camera_model")
            meta_row.width = meta_dict.get("width")
            meta_row.height = meta_dict.get("height")
            meta_row.duration_seconds = meta_dict.get("duration_seconds")
            meta_row.phash = phash

            session.commit()

        except Exception as e:
            session.rollback()
            stats["errors"] += 1
            log.error(f"Failed to index {path}: {e}", exc_info=True)

    # Duplicate detection pass
    _progress(total, total, "Detecting duplicates…")
    try:
        new_pairs = find_duplicates(session)
        for fid_a, fid_b, distance in new_pairs:
            session.add(Duplicate(file_id_a=fid_a, file_id_b=fid_b, hash_distance=distance))
        session.commit()
        if new_pairs:
            log.info(f"Found {len(new_pairs)} new duplicate pair(s)")
    except Exception as e:
        session.rollback()
        log.error(f"Duplicate detection failed: {e}", exc_info=True)

    _progress(total, total, "Done")
    log.info(f"Index complete: {stats}")
    return stats
