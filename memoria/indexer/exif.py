import logging
from datetime import datetime
from pathlib import Path

import exifread
from PIL import Image, UnidentifiedImageError

log = logging.getLogger(__name__)

PHOTO_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif",
    ".webp", ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw", ".dng",
}


def is_photo(filepath: str | Path) -> bool:
    return Path(filepath).suffix.lower() in PHOTO_EXTENSIONS


def extract_photo_metadata(filepath: str | Path) -> dict:
    """Return a dict of metadata for a photo file. Never raises — returns partial data on error."""
    path = Path(filepath)
    result = {
        "date_taken": None,
        "gps_lat": None,
        "gps_lon": None,
        "camera_make": None,
        "camera_model": None,
        "width": None,
        "height": None,
    }

    # Dimensions via Pillow (works on more formats than exifread)
    try:
        with Image.open(path) as img:
            result["width"], result["height"] = img.size
    except (UnidentifiedImageError, Exception) as e:
        log.warning(f"Pillow could not open {path}: {e}")

    # EXIF via exifread
    try:
        with open(path, "rb") as f:
            tags = exifread.process_file(f, stop_tag="GPS GPSLongitude", details=False)

        result["date_taken"] = _parse_date(tags)
        result["camera_make"] = _tag_str(tags, "Image Make")
        result["camera_model"] = _tag_str(tags, "Image Model")
        lat, lon = _parse_gps(tags)
        result["gps_lat"] = lat
        result["gps_lon"] = lon
    except Exception as e:
        log.warning(f"exifread failed on {path}: {e}")

    return result


def _tag_str(tags: dict, key: str) -> str | None:
    tag = tags.get(key)
    if tag is None:
        return None
    value = str(tag).strip()
    return value if value else None


def _parse_date(tags: dict) -> datetime | None:
    for key in ("EXIF DateTimeOriginal", "EXIF DateTimeDigitized", "Image DateTime"):
        tag = tags.get(key)
        if tag:
            try:
                return datetime.strptime(str(tag), "%Y:%m:%d %H:%M:%S")
            except ValueError:
                continue
    return None


def _dms_to_decimal(values, ref: str) -> float:
    """Convert degrees/minutes/seconds IFDRational list to decimal degrees."""
    d = float(values[0].num) / float(values[0].den)
    m = float(values[1].num) / float(values[1].den)
    s = float(values[2].num) / float(values[2].den)
    decimal = d + m / 60 + s / 3600
    if ref in ("S", "W"):
        decimal = -decimal
    return decimal


def _parse_gps(tags: dict) -> tuple[float | None, float | None]:
    try:
        lat_tag = tags.get("GPS GPSLatitude")
        lat_ref = tags.get("GPS GPSLatitudeRef")
        lon_tag = tags.get("GPS GPSLongitude")
        lon_ref = tags.get("GPS GPSLongitudeRef")

        if not all([lat_tag, lat_ref, lon_tag, lon_ref]):
            return None, None

        lat = _dms_to_decimal(lat_tag.values, str(lat_ref))
        lon = _dms_to_decimal(lon_tag.values, str(lon_ref))
        return lat, lon
    except Exception:
        return None, None
