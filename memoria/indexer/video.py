import logging
from datetime import datetime
from pathlib import Path

import ffmpeg

log = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v",
    ".mts", ".m2ts", ".3gp", ".flv", ".webm",
}


def is_video(filepath: str | Path) -> bool:
    return Path(filepath).suffix.lower() in VIDEO_EXTENSIONS


def extract_video_metadata(filepath: str | Path) -> dict:
    """Return a dict of metadata for a video file. Never raises — returns partial data on error."""
    path = Path(filepath)
    result = {
        "date_taken": None,
        "width": None,
        "height": None,
        "duration_seconds": None,
        "camera_make": None,
        "camera_model": None,
        "gps_lat": None,
        "gps_lon": None,
    }

    try:
        probe = ffmpeg.probe(str(path))
        fmt = probe.get("format", {})
        streams = probe.get("streams", [])

        # Duration
        duration = fmt.get("duration") or next(
            (s.get("duration") for s in streams if s.get("duration")), None
        )
        if duration:
            result["duration_seconds"] = float(duration)

        # Creation time
        tags = fmt.get("tags", {})
        for key in ("creation_time", "com.apple.quicktime.creationdate"):
            raw = tags.get(key)
            if raw:
                result["date_taken"] = _parse_video_date(raw)
                if result["date_taken"]:
                    break

        # Camera make/model (common in iPhone/Android videos)
        result["camera_make"] = tags.get("com.apple.quicktime.make") or tags.get("make")
        result["camera_model"] = tags.get("com.apple.quicktime.model") or tags.get("model")

        # GPS (some mobile videos embed location)
        location = tags.get("location") or tags.get("com.apple.quicktime.location.ISO6709")
        if location:
            lat, lon = _parse_iso6709(location)
            result["gps_lat"] = lat
            result["gps_lon"] = lon

        # Dimensions from first video stream
        for stream in streams:
            if stream.get("codec_type") == "video":
                result["width"] = stream.get("width")
                result["height"] = stream.get("height")
                break

    except ffmpeg.Error as e:
        log.warning(f"ffprobe failed on {path}: {e.stderr.decode() if e.stderr else e}")
    except Exception as e:
        log.warning(f"Video metadata extraction failed on {path}: {e}")

    return result


def _parse_video_date(raw: str) -> datetime | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw[:26], fmt)
        except ValueError:
            continue
    return None


def _parse_iso6709(location: str) -> tuple[float | None, float | None]:
    """Parse ISO 6709 location string e.g. '+51.5074-000.1278/'"""
    try:
        location = location.strip().rstrip("/")
        # Find the second sign character which separates lat from lon
        for i in range(1, len(location)):
            if location[i] in ("+", "-"):
                lat = float(location[:i])
                lon = float(location[i:])
                return lat, lon
    except Exception:
        pass
    return None, None
