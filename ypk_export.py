# path: ypk_export.py
"""Build a game-ready ``.ypk`` custom card pack.

A ``.ypk`` (YGOPro / mdpro3 expansion pack) is a plain ZIP archive with a fixed
layout, mirrored from the user-provided template:

    corres_srv.ini          pack metadata (preserved byte-for-byte)
    pack/                    (kept empty)
    pics/                    card render images, named <id>.<ext>
    pics/field/              (kept empty — field-spell backgrounds go here)
    script/                  card scripts, named c<id>.lua
    <packname>.cdb           the card database, at the archive root

We assemble it with :mod:`zipfile`: build the ``.cdb`` (via
:func:`cdb_export.build_cdb`), then drop in each card's Lua script and render
image keyed by its passcode. Image bytes are resolved from the same references
the site already stores (a path under ``static/`` or an absolute URL).
"""

import ipaddress
import os
import socket
import tempfile
import zipfile
from urllib.parse import urlsplit
from urllib.request import urlopen

from flask import current_app

from cdb_export import build_cdb

# The pack metadata file, preserved exactly from the reference template so our
# packs stay compatible with the manual WinRAR workflow.
_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "ypk_template")
_CORRES_SRV_PATH = os.path.join(_TEMPLATE_DIR, "corres_srv.ini")

# Structural empty directories the template carries.
_EMPTY_DIRS = ("pack/", "pics/", "pics/field/", "script/")

_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}


def _corres_srv_bytes():
    with open(_CORRES_SRV_PATH, "rb") as fh:
        return fh.read()


def _image_ext(ref):
    tail = ref.rsplit(".", 1)[-1].lower().split("?")[0] if "." in ref else ""
    return tail if tail in _IMAGE_EXTS else "jpg"


def _is_public_url(url):
    """SSRF guard for a *user-supplied* image URL.

    A card's ``render_image`` can be any http(s) URL the user typed, and we
    fetch it server-side when building a pack. Without this check a user could
    point it at an internal address (cloud metadata at 169.254.169.254,
    localhost, a private 10.x service…) and have the server fetch it and hand
    the bytes back inside the downloaded ``.ypk``.

    We allow only http/https and refuse any host that resolves to a private,
    loopback, link-local, or otherwise non-public address."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 0,
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return False
    return True


def resolve_image(ref):
    """Return ``(bytes, ext)`` for a render-image reference, or ``None``.

    Mirrors how the site resolves images elsewhere: an absolute URL is fetched
    (only if it points at a public host — see :func:`_is_public_url`); anything
    else is read from disk relative to ``static/``."""
    if not ref:
        return None
    if "://" in ref:
        if not _is_public_url(ref):
            return None
        try:
            with urlopen(ref, timeout=20) as resp:  # noqa: S310 (host vetted above)
                return resp.read(), _image_ext(ref)
        except Exception:
            return None
    path = os.path.join(current_app.static_folder, ref)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        return fh.read(), _image_ext(ref)


def normalize_lua(text):
    """Tidy a script for writing: LF line-endings, no surrounding blank lines,
    exactly one trailing newline. Internal indentation is left untouched."""
    body = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return (body + "\n").encode("utf-8") if body else b""


def build_ypk(path, pack_name, items):
    """Write a ``.ypk`` at ``path``.

    ``items`` is an iterable of ``(cdb_id, Card)`` pairs (the cards to pack).
    ``pack_name`` is the sanitised base name used for the inner ``.cdb``.
    Returns a small summary dict (counts) for user feedback.
    """
    items = list(items)
    scripts = images = 0

    cdb_fd, cdb_path = tempfile.mkstemp(suffix=".cdb")
    os.close(cdb_fd)
    try:
        build_cdb(cdb_path, items)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("corres_srv.ini", _corres_srv_bytes())
            for d in _EMPTY_DIRS:
                z.writestr(d, b"")                      # preserve folder layout
            z.write(cdb_path, arcname=f"{pack_name}.cdb")

            for cdb_id, card in items:
                lua = normalize_lua(getattr(card, "script", None))
                if lua:
                    z.writestr(f"script/c{cdb_id}.lua", lua)
                    scripts += 1
                img = resolve_image(card.render_image)
                if img:
                    data, ext = img
                    z.writestr(f"pics/{cdb_id}.{ext}", data)
                    images += 1
    finally:
        os.remove(cdb_path)

    return {"cards": len(items), "scripts": scripts, "images": images}
