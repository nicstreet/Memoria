import hashlib
import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError

log = logging.getLogger(__name__)

DUPLICATE_THRESHOLD = 10   # hamming distance; 0 = identical, ≤10 = likely duplicate
SIZE_RATIO_MAX = 4.0       # skip pairs where larger/smaller file size ratio exceeds this


def compute_phash(filepath: str | Path) -> str | None:
    """Return perceptual hash hex string for an image, or None on failure."""
    try:
        import imagehash
        with Image.open(filepath) as img:
            return str(imagehash.phash(img))
    except UnidentifiedImageError:
        log.debug(f"Cannot hash (unrecognised image): {filepath}")
        return None
    except Exception as e:
        log.warning(f"Phash failed for {filepath}: {e}")
        return None


def compute_md5(filepath: str | Path) -> str | None:
    """Return MD5 hex digest of file contents, or None on failure."""
    try:
        h = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        log.warning(f"MD5 failed for {filepath}: {e}")
        return None


def find_duplicates(session, threshold: int = DUPLICATE_THRESHOLD) -> list[tuple[int, int, int]]:
    """
    Compare all phashes in the metadata table and return new duplicate pairs.
    Returns list of (file_id_a, file_id_b, distance) with file_id_a < file_id_b.
    Skips pairs already recorded in the duplicates table.
    Skips pairs where file size ratio exceeds SIZE_RATIO_MAX.
    """
    import imagehash
    from memoria.database.models import Duplicate, File, Metadata

    # Load all hashed files with their sizes
    rows = (
        session.query(Metadata.file_id, Metadata.phash, File.size_bytes)
        .join(File, File.id == Metadata.file_id)
        .filter(Metadata.phash.isnot(None))
        .all()
    )

    if len(rows) < 2:
        return []

    # Load existing duplicate pairs to avoid re-inserting
    existing = set(
        session.query(Duplicate.file_id_a, Duplicate.file_id_b).all()
    )

    hashes = [
        (file_id, imagehash.hex_to_hash(phash), size_bytes or 0)
        for file_id, phash, size_bytes in rows
    ]
    new_pairs: list[tuple[int, int, int]] = []

    for i in range(len(hashes)):
        fid_a, hash_a, size_a = hashes[i]
        for j in range(i + 1, len(hashes)):
            fid_b, hash_b, size_b = hashes[j]

            # Skip if file sizes are wildly different
            if size_a > 0 and size_b > 0:
                ratio = max(size_a, size_b) / min(size_a, size_b)
                if ratio > SIZE_RATIO_MAX:
                    continue

            distance = hash_a - hash_b
            if distance <= threshold:
                pair = (min(fid_a, fid_b), max(fid_a, fid_b))
                if pair not in existing:
                    new_pairs.append((pair[0], pair[1], distance))

    return new_pairs
