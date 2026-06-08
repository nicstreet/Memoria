"""
AI Caption Generation
─────────────────────
Sends a photo + available metadata context to an AI vision API and
returns structured Title and Subject suggestions.

Currently supported providers:  Google Gemini
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

log = logging.getLogger(__name__)

_SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}

GEMINI_MODELS = [
    "gemini-2.0-flash-lite-001",  # fastest / cheapest (stable)
    "gemini-2.0-flash",           # good balance
    "gemini-2.5-flash-lite",      # efficient, latest gen
    "gemini-2.5-flash",           # best quality for photo analysis
    "gemini-2.5-pro",             # highest quality
]

_PROMPT = """\
Analyse this photo and return a JSON object with exactly two fields:
- "title": a concise, natural-language title (5–12 words; do not start with \
"A photo of" or "An image of"). The title should reflect both what is \
specifically visible in this photo AND the broader event or trip context \
if one is provided below.
- "subject": a single subject category — one to three words that best describes \
the photo's main theme (e.g. "Holiday", "Family Portrait", "Landscape", \
"Street Photography", "Wildlife", "Architecture", "Sport", "Event"). \
Keep the subject consistent with other photos from the same event.

{context}

Return ONLY a valid JSON object — no markdown fences, no explanation.
Example: {{"title": "Children building sandcastles at low tide", "subject": "Holiday"}}"""

_PROMPT_LOCKED_SUBJECT = """\
Analyse this photo and return a JSON object with exactly two fields:
- "title": a concise, natural-language title (5–12 words; do not start with \
"A photo of" or "An image of"). The title should reflect both what is \
specifically visible in this photo AND the broader event or trip context \
if one is provided below.
- "subject": use exactly "{locked_subject}" — this has already been decided \
for the whole batch, do not change it.

{context}

Return ONLY a valid JSON object — no markdown fences, no explanation.
Example: {{"title": "Eiffel Tower lit up at night during Paris trip", "subject": "{locked_subject}"}}"""

_BATCH_SUBJECT_PROMPT = """\
I will show you {n} photos from the same event or shoot.
Your task: pick ONE subject category that best describes the overall collection.

Choose from this list (pick the single best match):
{subject_list}

Return ONLY a JSON object with a single field:
{{"subject": "chosen subject"}}

No explanation, no markdown fences."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resize_to_bytes(filepath: str, max_px: int = 1024) -> bytes:
    """Return JPEG bytes of the image with longest edge capped at max_px."""
    from PIL import Image
    with Image.open(filepath) as img:
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_px:
            scale = max_px / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()


def _build_context(metadata: dict, batch_context: str = "") -> str:
    """Format available metadata into a bullet-point context block."""
    parts = []

    # Batch / event context goes first so the model weights it highly
    if batch_context:
        parts.append(f"Event / batch context: {batch_context}")

    if metadata.get("location_label"):
        parts.append(f"Location: {metadata['location_label']}")
    elif metadata.get("gps_lat") and metadata.get("gps_lon"):
        parts.append(
            f"GPS coordinates: {metadata['gps_lat']:.5f}°N, "
            f"{metadata['gps_lon']:.5f}°E"
        )

    if metadata.get("date_taken"):
        from datetime import datetime
        dt = metadata["date_taken"]
        if isinstance(dt, datetime):
            parts.append(f"Date & time: {dt.strftime('%d %B %Y at %H:%M')}")

    if metadata.get("people"):
        names = [n for n in metadata["people"] if n.lower() != "unknown"]
        if names:
            parts.append(f"People identified in photo: {', '.join(names)}")

    if metadata.get("tags"):
        clean = [t for t in metadata["tags"] if t.lower() != "unknown"]
        if clean:
            parts.append(f"Existing tags: {', '.join(clean)}")

    if not parts:
        return ""
    return "Context about this photo:\n" + "\n".join(f"- {p}" for p in parts)


def _parse_json_response(text: str) -> dict:
    """Parse JSON from model output, stripping any markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        # Remove opening fence (```json or ```) and closing fence
        lines = text.splitlines()
        inner = [
            l for l in lines[1:]
            if not l.strip().startswith("```")
        ]
        text = "\n".join(inner).strip()
    return json.loads(text)


# ── Provider: Google Gemini ───────────────────────────────────────────────────

def detect_batch_subject(
    filepaths: list[str],
    api_key: str,
    model: str = "gemini-2.0-flash-lite-001",
    batch_context: str = "",
    subject_list: list[str] | None = None,
) -> str:
    """
    Send up to 5 sample images to the AI and ask it to pick one subject
    category for the whole batch.  Returns the subject string.
    """
    if subject_list is None:
        from memoria.ui.default_subjects import ALL_SUBJECTS
        subject_list = ALL_SUBJECTS

    samples = filepaths[:5]
    parts: list[dict] = []

    ctx_line = f"\nBatch context: {batch_context}" if batch_context else ""
    prompt = _BATCH_SUBJECT_PROMPT.format(
        n=len(samples),
        subject_list="\n".join(f"- {s}" for s in subject_list),
    ) + ctx_line

    parts.append({"text": prompt})
    for fp in samples:
        try:
            ext = Path(fp).suffix.lower()
            if ext in _SUPPORTED_EXTS:
                img_b64 = base64.b64encode(_resize_to_bytes(fp)).decode()
                parts.append({"inline_data": {"mime_type": "image/jpeg", "data": img_b64}})
        except Exception:
            pass

    payload = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 64},
    }).encode()

    api_ver = "v1beta"
    url = (
        f"https://generativelanguage.googleapis.com/{api_ver}/models/"
        f"{model}:generateContent?key={api_key}"
    )
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        raw = data["candidates"][0]["content"]["parts"][0]["text"]
        result = _parse_json_response(raw)
        return str(result.get("subject", "")).strip()
    except Exception as exc:
        raise RuntimeError(f"Batch subject detection failed: {exc}") from exc


def generate_gemini(
    filepath: str,
    metadata: dict,
    api_key: str,
    model: str = "gemini-2.0-flash-lite-001",
    batch_context: str = "",
    locked_subject: str = "",
) -> dict:
    """
    Call the Gemini vision API for one photo.
    Returns {"title": str, "subject": str}.
    Raises RuntimeError on API error, ValueError for unsupported formats.
    """
    ext = Path(filepath).suffix.lower()
    if ext not in _SUPPORTED_EXTS:
        raise ValueError(f"Unsupported image format: {ext}")

    img_b64 = base64.b64encode(_resize_to_bytes(filepath)).decode()
    context = _build_context(metadata, batch_context=batch_context)
    if locked_subject:
        prompt = _PROMPT_LOCKED_SUBJECT.format(
            locked_subject=locked_subject, context=context
        )
    else:
        prompt = _PROMPT.format(context=context)

    payload = json.dumps({
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
        ]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 256},
    }).encode()

    # v1beta supports all model aliases including -latest; always use it
    api_ver = "v1beta"
    url = (
        f"https://generativelanguage.googleapis.com/{api_ver}/models/"
        f"{model}:generateContent?key={api_key}"
    )
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise RuntimeError(f"Gemini API error {exc.code}: {body}") from exc

    raw = data["candidates"][0]["content"]["parts"][0]["text"]
    result = _parse_json_response(raw)
    return {
        "title":   str(result.get("title",   "")).strip(),
        "subject": str(result.get("subject", "")).strip(),
    }


# ── Public entry point ────────────────────────────────────────────────────────

def generate_caption(
    filepath: str,
    metadata: dict,
    api_key: str,
    provider: str = "gemini",
    model: str = "gemini-2.0-flash-lite-001",
    batch_context: str = "",
    locked_subject: str = "",
) -> dict:
    """
    Generate title and subject for a photo using an AI vision API.

    Parameters
    ----------
    filepath : path to the image file
    metadata : dict with optional keys: location_label, gps_lat, gps_lon,
               date_taken (datetime), people (list[str]), tags (list[str])
    api_key  : provider API key
    provider : "gemini" (only supported provider currently)
    model    : model name string

    Returns
    -------
    {"title": str, "subject": str}
    """
    if provider == "gemini":
        return generate_gemini(filepath, metadata, api_key, model,
                               batch_context=batch_context,
                               locked_subject=locked_subject)
    raise NotImplementedError(f"Provider '{provider}' is not yet supported")
