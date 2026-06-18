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


def save_upload(file_storage):
    """Persist one uploaded file; return its DB reference string."""
    if not file_storage or not file_storage.filename:
        raise UploadError("No file provided.")
    ext = _ext(file_storage.filename)
    key = f"{uuid.uuid4().hex}.{ext}"          # random name = no collisions/overwrites

    if current_app.config.get("UPLOAD_BACKEND", "local") == "s3":
        return _save_s3(file_storage, key, ext)
    return _save_local(file_storage, key)


def _save_local(file_storage, key):
    subdir = current_app.config.get("UPLOAD_SUBDIR", "uploads")
    dest_dir = os.path.join(current_app.static_folder, subdir)
    os.makedirs(dest_dir, exist_ok=True)
    file_storage.save(os.path.join(dest_dir, key))
    return f"{subdir}/{key}"                    # resolved later via url_for('static', ...)


def _save_s3(file_storage, key, ext):
    import boto3  # lazy import: only needed for the s3/R2 backend

    cfg = current_app.config
    client = boto3.session.Session().client(
        "s3",
        endpoint_url=cfg.get("S3_ENDPOINT_URL") or None,   # set this for R2
        region_name=cfg.get("S3_REGION") or "auto",
    )
    client.upload_fileobj(
        file_storage.stream, cfg["S3_BUCKET"], key,
        ExtraArgs={"ContentType": _CONTENT_TYPE.get(ext, "application/octet-stream")},
    )
    base = (cfg.get("S3_PUBLIC_BASE") or "").rstrip("/")
    return f"{base}/{key}"