# path: blueprints/github.py
"""The 'github' blueprint: a thin, safe proxy to GitHub's public REST API used
by the card editor's "Import .lua from GitHub" widget.

The browser never talks to GitHub directly — these endpoints do, server-side,
so we can (a) keep an optional ``GITHUB_TOKEN`` private, (b) sidestep CORS, and
(c) validate every owner/repo/ref/path before it touches a URL. Only
``api.github.com`` is ever contacted, and only ``.lua`` files are returned.

It also stores each user's *remembered* import locations (repo + folder) on the
``User`` row, so the same place is one click away next time.
"""

import base64
import json
import re
from datetime import datetime
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from extensions import db

github_bp = Blueprint("github", __name__)

_API_ROOT = "https://api.github.com"
# GitHub owner/repo names: alphanumerics plus -, _, and . (repos allow dots).
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
# A git ref (branch/tag): conservative but covers slashes in branch names.
_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
# Cap on a fetched script — the contents API only inlines files up to ~1 MB and
# a card script is tiny; refuse anything implausibly large.
_MAX_LUA_BYTES = 512 * 1024
# How many remembered locations to keep per user (most-recent-first).
_MAX_SOURCES = 12


class GithubError(Exception):
    """A user-facing failure talking to GitHub, carrying an HTTP status."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.message = message
        self.status = status


# --------------------------------------------------------------------- helpers
def _err(message, status):
    return jsonify(error=message), status


def _valid_path(path):
    """Normalise and validate a repo-relative path. Empty is the repo root.
    Rejects absolute paths and ``..`` traversal (defence-in-depth — GitHub
    would reject them too, but we never want to construct such a URL)."""
    path = (path or "").strip().strip("/")
    if not path:
        return ""
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise GithubError("Invalid path.", 400)
    return path


def _http_error_message(exc):
    """Turn an HTTPError from GitHub into a friendly sentence."""
    if exc.code == 404:
        return "Not found on GitHub — check the username, repository, and branch."
    if exc.code in (401, 403):
        # 403 is almost always the unauthenticated rate limit.
        remaining = exc.headers.get("X-RateLimit-Remaining") if exc.headers else None
        if remaining == "0":
            return ("GitHub rate limit reached. Try again later, or set a "
                    "GITHUB_TOKEN on the server for higher limits.")
        return "GitHub denied the request (private repo or rate limit)."
    return f"GitHub returned an error (HTTP {exc.code})."


def _gh_get(path, params=None):
    """GET a GitHub REST API path and return parsed JSON. Raises GithubError.

    ``path`` must already be URL-safe (callers quote dynamic segments). Only the
    fixed ``api.github.com`` host is ever contacted."""
    url = _API_ROOT + path
    if params:
        url += "?" + urlencode(params)
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "TheCustomDuelist-CardEditor",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = (current_app.config.get("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    timeout = current_app.config.get("GITHUB_API_TIMEOUT", 15)
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed host)
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raise GithubError(_http_error_message(exc), 502 if exc.code >= 500 else exc.code)
    except (URLError, TimeoutError):
        raise GithubError("Couldn't reach GitHub. Check the connection and retry.", 502)
    except ValueError:
        raise GithubError("GitHub returned an unexpected response.", 502)


def _repo_summary(r):
    return {
        "name": r.get("name", ""),
        "full_name": r.get("full_name", ""),
        "default_branch": r.get("default_branch", "main"),
        "private": bool(r.get("private")),
        "description": r.get("description") or "",
        "pushed_at": r.get("pushed_at") or "",
    }


def _list_repos(owner):
    """Public repos for a user, falling back to the org endpoint. Newest pushes
    first so the repos you actually work in surface at the top."""
    params = {"per_page": 100, "sort": "pushed", "type": "owner"}
    try:
        data = _gh_get(f"/users/{quote(owner)}/repos", params)
    except GithubError as exc:
        if exc.status == 404:
            data = _gh_get(f"/orgs/{quote(owner)}/repos", {"per_page": 100, "sort": "pushed"})
        else:
            raise
    if not isinstance(data, list):
        return []
    return [_repo_summary(r) for r in data]


def _contents_path(owner, repo, path):
    safe = quote(path, safe="/") if path else ""
    return f"/repos/{quote(owner)}/{quote(repo)}/contents/{safe}"


def _is_lua(name):
    return name.lower().endswith(".lua")


# --- remembered locations (stored on the User row) -------------------------
def _get_sources():
    return list(current_user.lua_import_sources or [])


def _source_key(s):
    return (s.get("owner", ""), s.get("repo", ""), s.get("ref", ""), s.get("path", ""))


def _read_location(body):
    """Validate the {owner, repo, ref, path} of a remembered location."""
    owner = (body.get("owner") or "").strip()
    repo = (body.get("repo") or "").strip()
    ref = (body.get("ref") or "").strip()
    if not (_NAME_RE.match(owner) and _NAME_RE.match(repo)):
        raise GithubError("A valid owner and repository are required.", 400)
    if ref and not _REF_RE.match(ref):
        raise GithubError("Invalid branch name.", 400)
    return owner, repo, ref, _valid_path(body.get("path"))


# ---------------------------------------------------------------------- routes
@github_bp.route("/repos")
@login_required
def repos():
    owner = (request.args.get("owner") or "").strip()
    if not _NAME_RE.match(owner):
        return _err("Enter a GitHub username or organization.", 400)
    try:
        return jsonify(repos=_list_repos(owner))
    except GithubError as exc:
        return _err(exc.message, exc.status)


@github_bp.route("/repo")
@login_required
def repo_meta():
    owner = (request.args.get("owner") or "").strip()
    repo = (request.args.get("repo") or "").strip()
    if not (_NAME_RE.match(owner) and _NAME_RE.match(repo)):
        return _err("Enter a valid owner and repository.", 400)
    try:
        data = _gh_get(f"/repos/{quote(owner)}/{quote(repo)}")
    except GithubError as exc:
        return _err(exc.message, exc.status)
    return jsonify(repo=_repo_summary(data))


@github_bp.route("/contents")
@login_required
def contents():
    owner = (request.args.get("owner") or "").strip()
    repo = (request.args.get("repo") or "").strip()
    ref = (request.args.get("ref") or "").strip()
    if not (_NAME_RE.match(owner) and _NAME_RE.match(repo)):
        return _err("Enter a valid owner and repository.", 400)
    if ref and not _REF_RE.match(ref):
        return _err("Invalid branch name.", 400)
    try:
        path = _valid_path(request.args.get("path"))
        data = _gh_get(_contents_path(owner, repo, path),
                       {"ref": ref} if ref else None)
    except GithubError as exc:
        return _err(exc.message, exc.status)
    if not isinstance(data, list):
        return _err("That path is a file, not a folder.", 400)

    # Folders first, then files; within each, .lua files float above the rest so
    # scripts are easy to spot. Non-lua files are kept (greyed out client-side)
    # for orientation but can't be imported.
    dirs, luas, others = [], [], []
    for e in data:
        item = {"name": e.get("name", ""), "path": e.get("path", ""),
                "type": e.get("type", ""), "size": e.get("size", 0),
                "is_lua": e.get("type") == "file" and _is_lua(e.get("name", ""))}
        if item["type"] == "dir":
            dirs.append(item)
        elif item["is_lua"]:
            luas.append(item)
        else:
            others.append(item)
    sort = lambda xs: sorted(xs, key=lambda i: i["name"].lower())
    return jsonify(path=path, entries=sort(dirs) + sort(luas) + sort(others))


@github_bp.route("/file")
@login_required
def file():
    owner = (request.args.get("owner") or "").strip()
    repo = (request.args.get("repo") or "").strip()
    ref = (request.args.get("ref") or "").strip()
    if not (_NAME_RE.match(owner) and _NAME_RE.match(repo)):
        return _err("Enter a valid owner and repository.", 400)
    if ref and not _REF_RE.match(ref):
        return _err("Invalid branch name.", 400)
    try:
        path = _valid_path(request.args.get("path"))
    except GithubError as exc:
        return _err(exc.message, exc.status)
    if not path or not _is_lua(path):
        return _err("Only .lua files can be imported.", 400)
    try:
        data = _gh_get(_contents_path(owner, repo, path),
                       {"ref": ref} if ref else None)
    except GithubError as exc:
        return _err(exc.message, exc.status)
    if isinstance(data, list):
        return _err("That path is a folder, not a file.", 400)
    if data.get("size", 0) > _MAX_LUA_BYTES:
        return _err("That file is too large to import.", 400)
    if data.get("encoding") != "base64" or "content" not in data:
        return _err("Couldn't read that file's contents from GitHub.", 502)
    try:
        text = base64.b64decode(data["content"]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return _err("That file isn't valid UTF-8 text.", 400)
    return jsonify(name=data.get("name", ""), path=data.get("path", path),
                   size=data.get("size", 0), content=text)


@github_bp.route("/sources")
@login_required
def list_sources():
    return jsonify(sources=_get_sources())


@github_bp.route("/sources", methods=["POST"])
@login_required
def add_source():
    body = request.get_json(silent=True) or {}
    try:
        owner, repo, ref, path = _read_location(body)
    except GithubError as exc:
        return _err(exc.message, exc.status)
    label = (body.get("label") or "").strip()[:160] or f"{owner}/{repo}"
    entry = {"owner": owner, "repo": repo, "ref": ref, "path": path,
             "label": label, "last_used": datetime.utcnow().isoformat(timespec="seconds")}
    # De-dupe on the location, move the latest to the front, keep a sane cap.
    sources = [s for s in _get_sources() if _source_key(s) != _source_key(entry)]
    sources.insert(0, entry)
    current_user.lua_import_sources = sources[:_MAX_SOURCES]
    db.session.commit()
    return jsonify(sources=current_user.lua_import_sources)


@github_bp.route("/sources/delete", methods=["POST"])
@login_required
def delete_source():
    body = request.get_json(silent=True) or {}
    try:
        owner, repo, ref, path = _read_location(body)
    except GithubError as exc:
        return _err(exc.message, exc.status)
    key = (owner, repo, ref, path)
    current_user.lua_import_sources = [
        s for s in _get_sources() if _source_key(s) != key]
    db.session.commit()
    return jsonify(sources=current_user.lua_import_sources)
