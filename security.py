# path: security.py
"""Small, dependency-free security helpers shared across blueprints.

Kept import-light (only the stdlib) so any module — including config-time code —
can use it without pulling in Flask or the app.
"""

from urllib.parse import urlsplit


def _strip_control(target):
    """Return the trimmed target, or "" if it carries ASCII control characters
    (newlines, tabs, NUL, DEL…). Those never belong in a redirect target and
    are a classic response-splitting / guard-evasion trick."""
    if not target:
        return ""
    t = target.strip()
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in t):
        return ""
    return t


def normalize_redirect_target(target):
    """Normalise a user-supplied redirect target for safe analysis.

    Browsers treat a backslash as a forward slash in URLs, so ``/\\evil.com`` is
    really ``//evil.com`` — a protocol-relative link to another origin. A guard
    that only inspects ``urlsplit().netloc`` or a leading ``//`` is bypassed
    unless we fold backslashes to slashes *before* parsing. Returns "" for
    empty or control-tainted input.
    """
    t = _strip_control(target)
    return t.replace("\\", "/")


def is_same_site_path(target):
    """True only for a plain, same-site *relative* path (``/foo?bar``): no
    scheme, no host, and not protocol-relative (``//host``). Backslash tricks
    are folded first via :func:`normalize_redirect_target`."""
    t = normalize_redirect_target(target)
    if not t:
        return False
    parts = urlsplit(t)
    if parts.scheme or parts.netloc:
        return False
    return t.startswith("/") and not t.startswith("//")
