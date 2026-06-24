# path: config.py
"""Configuration lives in its own module so settings are separated from logic.

You point the app at a config object with `app.config.from_object(Config)`.
In real projects you'd subclass this (DevConfig, ProdConfig) and pick one via
an environment variable. Here we keep a single class for clarity.
"""

import os
from datetime import timedelta

# Dev mode unless explicitly disabled. Gates "secure-cookie" settings so login
# still works over plain http locally.
_DEBUG = os.environ.get("FLASK_DEBUG", "1") == "1"
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