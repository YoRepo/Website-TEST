# path: config.py
"""Configuration lives in its own module so settings are separated from logic.

You point the app at a config object with `app.config.from_object(Config)`.
In real projects you'd subclass this (DevConfig, ProdConfig) and pick one via
an environment variable. Here we keep a single class for clarity.
"""

import os
from datetime import timedelta

# Production-safe by default: debug is OFF unless you explicitly opt in with
# FLASK_DEBUG=1. This gates the "secure-cookie" settings below, so a forgotten
# env var fails safe (HTTPS-only cookies) instead of shipping relaxed ones.
# `python app.py` sets FLASK_DEBUG=1 for you; for `flask run` during local
# development, export FLASK_DEBUG=1 so login works over plain http.
_DEBUG = os.environ.get("FLASK_DEBUG") == "1"
_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///customduelist.db")
# Render gives "postgres://", SQLAlchemy wants "postgresql://". Fix transparently
# so the same code runs locally (SQLite) and on Render (Postgres).
if _DATABASE_URL.startswith("postgres://"):
    _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)


class Config:
    SITE_NAME = "TheCustomDuelist"
    SITE_TAGLINE = "Custom cards, presented."

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")

    SQLALCHEMY_DATABASE_URI = _DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Flip to "0" (env var) or change this default to start empty —
    # no demo users, cards, or articles. Only affects a fresh/empty DB.
    SEED_DEMO_DATA = os.environ.get("SEED_DEMO_DATA", "1") == "1"

    # --- Uploads ---------------------------------------------------------
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "8")) * 1024 * 1024
    UPLOAD_BACKEND = os.environ.get("UPLOAD_BACKEND", "local")  # "local" | "s3"
    UPLOAD_SUBDIR = os.environ.get("UPLOAD_SUBDIR", "uploads")  # under static/
    # Only used when UPLOAD_BACKEND == "s3":
    S3_BUCKET = os.environ.get("S3_BUCKET", "")
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "")  # R2: https://<acct>.r2.cloudflarestorage.com
    S3_PUBLIC_BASE = os.environ.get("S3_PUBLIC_BASE", "")  # public URL base for objects
    S3_REGION = os.environ.get("S3_REGION", "auto")

    # --- Optional upload image scanning ----------------------------------
    # When enabled, every *sanitised* image is POSTed to IMAGE_SCAN_WEBHOOK_URL
    # for classification before it is stored. The endpoint must reply HTTP 200
    # with JSON {"allowed": true|false}. Anything else (error, timeout, non-200,
    # unparseable body) counts as "couldn't verify"; the upload is then REFUSED
    # unless IMAGE_SCAN_FAIL_OPEN=1. This is the seam to wire in a CSAM/abuse
    # classifier (PhotoDNA/Thorn, a homemade model, a moderation API…) without
    # touching app code. See docs/DEPLOYMENT.md.
    IMAGE_SCAN_ENABLED = os.environ.get("IMAGE_SCAN_ENABLED", "0") == "1"
    IMAGE_SCAN_WEBHOOK_URL = os.environ.get("IMAGE_SCAN_WEBHOOK_URL", "")
    IMAGE_SCAN_TIMEOUT = int(os.environ.get("IMAGE_SCAN_TIMEOUT", "10"))
    IMAGE_SCAN_FAIL_OPEN = os.environ.get("IMAGE_SCAN_FAIL_OPEN", "0") == "1"

    # --- Rate limiting ---------------------------------------------------
    # In-memory works for one instance but resets on restart and can't be shared
    # across workers/instances. Point this at Redis in production so throttles
    # survive deploys and span processes, e.g. redis://:password@host:6379/0.
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    # --- Trust & safety --------------------------------------------------
    # Shown on the policy pages and used as the abuse/DMCA contact. CHANGE THIS
    # before launch (a real, monitored inbox you can act on quickly).
    SITE_CONTACT_EMAIL = os.environ.get("SITE_CONTACT_EMAIL", "abuse@example.com")

    # Hold new uploads from non-staff users for moderator approval before they
    # go public. Opt-in — off preserves instant publishing. Reuses the takedown
    # (is_hidden) plumbing: pending content is hidden with no takedown author,
    # and a moderator "approves" it by unhiding. See blueprints/moderation.py.
    REQUIRE_UPLOAD_REVIEW = os.environ.get("REQUIRE_UPLOAD_REVIEW", "0") == "1"

    # Error monitoring: set SENTRY_DSN (and `pip install sentry-sdk`) to enable.
    SENTRY_DSN = os.environ.get("SENTRY_DSN", "")

    # --- GitHub script import --------------------------------------------
    # Optional. Unset works fine for public repos (GitHub allows 60 anonymous
    # API requests/hour/IP). Set a fine-grained or classic PAT to raise that
    # limit (and to read private repos). Used only server-side by the card
    # editor's "Import .lua from GitHub" widget — never exposed to the browser.
    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
    GITHUB_API_TIMEOUT = int(os.environ.get("GITHUB_API_TIMEOUT", "15"))

    # --- Session / cookie hardening --------------------------------------
    SESSION_COOKIE_HTTPONLY = True            # JS cannot read the session cookie
    SESSION_COOKIE_SAMESITE = "Lax"           # CSRF defence-in-depth
    SESSION_COOKIE_SECURE = not _DEBUG        # HTTPS-only off-dev
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = not _DEBUG
    REMEMBER_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)
    WTF_CSRF_TIME_LIMIT = None                # token lives as long as the session