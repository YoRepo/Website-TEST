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


class UploadError(Exception):
    """A bad upload — safe to show to the user."""


def _ext(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXT:
        raise UploadError("Unsupported image type — use PNG, JPG, GIF, or WEBP.")
    return ext


def save_upload(file_storage, crop_aspect=None):
    """Persist one uploaded file; return its DB reference string.

    `crop_aspect` — optional (w, h) tuple. When given, the image is
    center-cropped to that aspect ratio before storage, so the saved file
    shows just the card (matching the `object-fit: cover` display boxes)
    instead of the uploaded image's side/top margins.
    """
    if not file_storage or not file_storage.filename:
        raise UploadError("No file provided.")
    ext = _ext(file_storage.filename)
    key = f"{uuid.uuid4().hex}.{ext}"          # random name = no collisions/overwrites

    data = _center_crop_to_aspect(file_storage, ext, crop_aspect) if crop_aspect else None

    if current_app.config.get("UPLOAD_BACKEND", "local") == "s3":
        return _save_s3(file_storage, key, ext, data)
    return _save_local(file_storage, key, data)


def _center_crop_to_aspect(file_storage, ext, aspect):
    """Return a BytesIO of the image center-cropped to `aspect` (w, h), or
    None to fall back to saving the original bytes untouched (non-decodable
    or animated images, which we never want to flatten)."""
    from PIL import Image, ImageOps  # lazy: only needed when cropping

    try:
        img = Image.open(file_storage.stream)
        img.load()
    except Exception:
        file_storage.stream.seek(0)            # let the backend store it raw
        return None
    if getattr(img, "is_animated", False):     # don't drop frames from animated GIF/WEBP
        file_storage.stream.seek(0)
        return None

    img = ImageOps.exif_transpose(img)         # honour camera/phone orientation
    w, h = img.size
    target = aspect[0] / aspect[1]
    if w / h > target:                         # too wide → trim left/right
        new_w = round(h * target)
        x0 = (w - new_w) // 2
        box = (x0, 0, x0 + new_w, h)
    else:                                      # too tall → trim top/bottom
        new_h = round(w / target)
        y0 = (h - new_h) // 2
        box = (0, y0, w, y0 + new_h)
    img = img.crop(box)

    buf = io.BytesIO()
    fmt = "JPEG" if ext in ("jpg", "jpeg") else ext.upper()
    save_kwargs = {}
    if fmt == "JPEG":
        img = img.convert("RGB")               # JPEG can't hold an alpha channel
        save_kwargs["quality"] = 90
    img.save(buf, format=fmt, **save_kwargs)
    buf.seek(0)
    return buf


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
    client.upload_fileobj(
        data if data is not None else file_storage.stream, cfg["S3_BUCKET"], key,
        ExtraArgs={"ContentType": _CONTENT_TYPE.get(ext, "application/octet-stream")},
    )
    base = (cfg.get("S3_PUBLIC_BASE") or "").rstrip("/")
    return f"{base}/{key}"