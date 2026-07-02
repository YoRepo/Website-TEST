# path: storage.py
"""Pluggable image upload storage.

`save_upload(file_storage)` validates an uploaded image, stores it via the
configured backend, and returns a *reference string* for Card.art_image /
Card.render_image:

  • local backend → path relative to static/, e.g. "uploads/ab12...png"
  • s3/R2 backend → absolute URL, e.g. "https://cdn.example.com/ab12...png"

Both shapes are already understood wherever the app renders a card image
(CardSVG.resolveImageSrc in JS, and the url_for / '://' checks in templates),
so nothing downstream changes when you switch backends.

Security note
-------------
Every upload is *decoded and re-encoded* through Pillow before it is stored.
This is deliberate and load-bearing:

  • it proves the bytes are a genuine image of an allowed type (a file merely
    *named* ``evil.png`` that actually contains HTML/JS is rejected);
  • it strips all metadata — including EXIF GPS coordinates from phone photos —
    so users don't unknowingly republish their location;
  • it neutralises "polyglot" files (bytes valid as both an image and as
    script/HTML) because the stored file is freshly produced by Pillow.

We never fall back to storing the raw upload: if Pillow can't decode it, the
upload is refused.
"""

import io
import os
import uuid

from flask import current_app

ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
_CONTENT_TYPE = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp",
}
# Pillow format name keyed by file extension (used when re-encoding).
_PIL_FORMAT = {
    "png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "gif": "GIF", "webp": "WEBP",
}
# Skip cropping when the image is already this close to the target ratio, so a
# correctly-proportioned render isn't needlessly re-cropped over a stray pixel.
_ASPECT_TOLERANCE = 0.01


class UploadError(Exception):
    """A bad upload — safe to show to the user."""


def _ext(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise UploadError("Unsupported image type — use PNG, JPG, GIF, or WEBP.")
    return ext


def save_upload(file_storage, crop_aspect=None):
    """Persist one uploaded file; return its DB reference string.

    The upload is always decoded and re-encoded through Pillow (see the module
    docstring). `crop_aspect` (width / height) additionally center-crops the
    image first, the same way the card widgets `object-fit: cover` it at display
    time — so a square upload with the card centred and side margins is trimmed
    down to just the card.
    """
    if not file_storage or not file_storage.filename:
        raise UploadError("No file provided.")
    ext = _ext(file_storage.filename)
    key = f"{uuid.uuid4().hex}.{ext}"          # random name = no collisions/overwrites

    data = _sanitize_image(file_storage, ext, crop_aspect)

    # Optional content scan (CSAM/abuse classifier) on the *clean* bytes, before
    # anything is persisted. No-op unless IMAGE_SCAN_ENABLED. Raises UploadError
    # to refuse a flagged (or unverifiable) upload.
    _scan_image(data, ext)

    if current_app.config.get("UPLOAD_BACKEND", "local") == "s3":
        return _save_s3(key, ext, data)
    return _save_local(key, data)


def _scan_image(data, ext):
    """Send the sanitised image to an external moderation endpoint for a
    keep/reject decision, when one is configured.

    The endpoint receives the raw image bytes (POST body, correct Content-Type)
    and must return HTTP 200 with JSON ``{"allowed": true|false}``. This is the
    integration seam for a CSAM/abuse classifier (PhotoDNA/Thorn, a hosted
    moderation API, or your own model). Disabled by default so nothing changes
    until you opt in.

    Fails CLOSED: if scanning is enabled but the endpoint errors, times out, or
    returns something unparseable, the upload is refused — better a false
    rejection than storing content you couldn't check. Set IMAGE_SCAN_FAIL_OPEN
    to flip that trade-off.
    """
    cfg = current_app.config
    if not cfg.get("IMAGE_SCAN_ENABLED"):
        return

    fail_open = bool(cfg.get("IMAGE_SCAN_FAIL_OPEN"))
    url = (cfg.get("IMAGE_SCAN_WEBHOOK_URL") or "").strip()
    if not url:
        if fail_open:
            return
        current_app.logger.error(
            "IMAGE_SCAN_ENABLED but IMAGE_SCAN_WEBHOOK_URL is unset.")
        raise UploadError(
            "Image moderation is temporarily unavailable — please try again later.")

    import json as _json
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError

    payload = data.getvalue()   # doesn't disturb the stream position for storage
    req = Request(
        url, data=payload, method="POST",
        headers={
            "Content-Type": _CONTENT_TYPE.get(ext, "application/octet-stream"),
            "User-Agent": "TheCustomDuelist-UploadScanner",
        },
    )
    try:
        with urlopen(req, timeout=cfg.get("IMAGE_SCAN_TIMEOUT", 10)) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        if fail_open:
            current_app.logger.warning("Image scan unavailable (%s); allowing.", exc)
            return
        current_app.logger.warning("Image scan unavailable (%s); refusing.", exc)
        raise UploadError(
            "Couldn't verify this image right now — please try again shortly.")
    finally:
        data.seek(0)            # be explicit: hand a rewound stream to storage

    if not (isinstance(result, dict) and result.get("allowed") is True):
        raise UploadError("That image was rejected by automated moderation.")


def _sanitize_image(file_storage, ext, aspect=None):
    """Decode the upload with Pillow, optionally center-crop to `aspect`, then
    re-encode to a clean BytesIO (no original metadata). Raises UploadError if
    the bytes aren't a decodable image — we never store an unverified upload."""
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:                          # Pillow is a hard dependency
        raise UploadError(
            "Image processing is unavailable on the server. Please try later.")

    try:
        file_storage.stream.seek(0)
        img = Image.open(file_storage.stream)
        img.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise UploadError(
            "That file isn't a valid image — use a real PNG, JPG, GIF, or WEBP.")

    w, h = img.size
    if not w or not h:
        raise UploadError("That image has no dimensions.")

    # Center-crop to the requested aspect ratio when asked (and not already there).
    if aspect:
        cur = w / h
        if abs(cur - aspect) / aspect >= _ASPECT_TOLERANCE:
            if cur > aspect:                     # too wide → trim the sides
                new_w = round(h * aspect)
                left = (w - new_w) // 2
                box = (left, 0, left + new_w, h)
            else:                                # too tall → trim top and bottom
                new_h = round(w / aspect)
                top = (h - new_h) // 2
                box = (0, top, w, top + new_h)
            img = img.crop(box)

    return _encode(img, ext)


def _encode(img, ext):
    """Re-encode a Pillow image to a BytesIO in the target format. Preserves
    animation for multi-frame GIF/WEBP when possible; otherwise writes a single
    clean frame. The re-encode is what drops any original metadata."""
    from PIL import Image  # noqa: F401  (already importable; see _sanitize_image)

    fmt = _PIL_FORMAT.get(ext, "PNG")
    out = io.BytesIO()

    # Best-effort animation preservation: only meaningful when we haven't
    # cropped (cropping a multi-frame image would need per-frame work).
    n_frames = getattr(img, "n_frames", 1)
    if fmt in ("GIF", "WEBP") and n_frames > 1:
        try:
            img.save(out, format=fmt, save_all=True)
            out.seek(0)
            return out
        except Exception:
            out = io.BytesIO()                   # fall through to a single frame
            img.seek(0)

    save_kwargs = {}
    if fmt == "JPEG":
        img = img.convert("RGB")                 # JPEG has no alpha channel
        save_kwargs["quality"] = 95
    img.save(out, format=fmt, **save_kwargs)
    out.seek(0)
    return out


def _save_local(key, data):
    subdir = current_app.config.get("UPLOAD_SUBDIR", "uploads")
    dest_dir = os.path.join(current_app.static_folder, subdir)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, key)
    with open(dest, "wb") as fh:
        fh.write(data.getbuffer())
    return f"{subdir}/{key}"                     # resolved later via url_for('static', ...)


def _save_s3(key, ext, data):
    import boto3  # lazy import: only needed for the s3/R2 backend

    cfg = current_app.config
    client = boto3.session.Session().client(
        "s3",
        endpoint_url=cfg.get("S3_ENDPOINT_URL") or None,   # set this for R2
        region_name=cfg.get("S3_REGION") or "auto",
    )
    client.upload_fileobj(
        data, cfg["S3_BUCKET"], key,
        ExtraArgs={"ContentType": _CONTENT_TYPE.get(ext, "application/octet-stream")},
    )
    base = (cfg.get("S3_PUBLIC_BASE") or "").rstrip("/")
    return f"{base}/{key}"
