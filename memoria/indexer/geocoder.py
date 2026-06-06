import logging

log = logging.getLogger(__name__)

_rg = None  # lazy-loaded — first call triggers the offline data load (~1 second)


def _get_rg():
    global _rg
    if _rg is None:
        import reverse_geocoder as rg
        _rg = rg
    return _rg


def reverse_geocode(lat: float, lon: float) -> str | None:
    """Return a human-readable location label for GPS coordinates, or None on failure."""
    if lat is None or lon is None:
        return None
    try:
        rg = _get_rg()
        results = rg.search([(lat, lon)], verbose=False)
        if results:
            r = results[0]
            parts = [p for p in (r.get("name"), r.get("admin1"), r.get("cc")) if p]
            return ", ".join(parts) if parts else None
    except Exception as e:
        log.warning(f"Reverse geocode failed for ({lat}, {lon}): {e}")
    return None
