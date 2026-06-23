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
# Pillow format name keyed by file extension (used when re-encoding a crop).
_PIL_FORMAT = {
    "png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "gif": "GIF", "webp": "WEBP",
}
# Skip cropping when the image is already this close to the target ratio, so a
# correctly-proportioned render isn't needlessly re-encoded over a stray pixel.
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

    `crop_aspect` (width / height) center-crops the image before storing, the
    same way the card widgets `object-fit: cover` it at display time — so a
    square upload with the card centred and side margins is trimmed down to
    just the card. Falls back to the raw upload if Pillow is unavailable or the
    bytes aren't a decodable image.
    """
    if not file_storage or not file_storage.filename:
        raise UploadError("No file provided.")
    ext = _ext(file_storage.filename)
    key = f"{uuid.uuid4().hex}.{ext}"          # random name = no collisions/overwrites

    data = _crop_to_aspect(file_storage, ext, crop_aspect) if crop_aspect else None

    if current_app.config.get("UPLOAD_BACKEND", "local") == "s3":
        return _save_s3(file_storage, key, ext, data)
    return _save_local(file_storage, key, data)


def _crop_to_aspect(file_storage, ext, aspect):
    """Return a BytesIO of `file_storage` center-cropped to `aspect`, or None to
    store the upload untouched (Pillow missing, undecodable, or already on-ratio)."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        file_storage.stream.seek(0)
        img = Image.open(file_storage.stream)
        img.load()
    except Exception:
        return None
    w, h = img.size
    if not w or not h:
        return None

    cur = w / h
    if abs(cur - aspect) / aspect < _ASPECT_TOLERANCE:
        return None                              # already the card's proportions
    if cur > aspect:                             # too wide → trim the sides
        new_w = round(h * aspect)
        left = (w - new_w) // 2
        box = (left, 0, left + new_w, h)
    else:                                        # too tall → trim top and bottom
        new_h = round(w / aspect)
        top = (h - new_h) // 2
        box = (0, top, w, top + new_h)

    cropped = img.crop(box)
    fmt = _PIL_FORMAT.get(ext, img.format or "PNG")
    save_kwargs = {}
    if fmt == "JPEG":
        cropped = cropped.convert("RGB")         # JPEG has no alpha channel
        save_kwargs["quality"] = 95
    out = io.BytesIO()
    cropped.save(out, format=fmt, **save_kwargs)
    out.seek(0)
    return out


def _save_local(file_storage, key, data=None):
    subdir = current_app.config.get("UPLOAD_SUBDIR", "uploads")
    dest_dir = os.path.join(current_app.static_folder, subdir)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, key)
    if data is not None:
        with open(dest, "wb") as fh:
            fh.write(data.getbuffer())
    else:
        file_storage.save(dest)
    return f"{subdir}/{key}"                    # resolved later via url_for('static', ...)


def _save_s3(file_storage, key, ext, data=None):
    import boto3  # lazy import: only needed for the s3/R2 backend

    cfg = current_app.config
    client = boto3.session.Session().client(
        "s3",
        endpoint_url=cfg.get("S3_ENDPOINT_URL") or None,   # set this for R2
        region_name=cfg.get("S3_REGION") or "auto",
    )
    body = data if data is not None else file_storage.stream
    client.upload_fileobj(
        body, cfg["S3_BUCKET"], key,
        ExtraArgs={"ContentType": _CONTENT_TYPE.get(ext, "application/octet-stream")},
    )
    base = (cfg.get("S3_PUBLIC_BASE") or "").rstrip("/")
    return f"{base}/{key}"