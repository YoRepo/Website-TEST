# path: app.py
"""Entry point. Defines the application factory `create_app()`.

A factory lets you build multiple app instances with different configs
(essential for testing) and keeps top-level code free of side effects.
"""

import os

# Running `python app.py` directly means local development, so default to debug
# (which permits the dev SECRET_KEY and relaxed, non-secure cookies). Production
# imports this module instead (gunicorn loads `wsgi:app`), so __name__ != main
# there and the secure defaults stand unless FLASK_DEBUG is explicitly set. This
# MUST run before `config` is imported, since config reads FLASK_DEBUG at import.
if __name__ == "__main__":
    os.environ.setdefault("FLASK_DEBUG", "1")

import secrets

from flask import Flask, g, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from extensions import db, login_manager, csrf, limiter

def _ensure_card_columns():
    """Additive, idempotent migration for columns that post-date the original
    `card` table. `db.create_all()` creates missing *tables* but never ALTERs an
    existing one, so brand-new columns (setcodes, strings) must be added by hand
    on already-deployed databases. Safe to run on every boot."""
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    if "card" not in insp.get_table_names():
        return  # fresh DB: create_all() already built it with every column
    existing = {c["name"] for c in insp.get_columns("card")}
    wanted = {"cdb_id": "INTEGER", "setcodes": "JSON", "strings": "JSON",
              "script": "TEXT", "is_trap_monster": "BOOLEAN"}
    missing = {name: typ for name, typ in wanted.items() if name not in existing}
    if not missing:
        return
    with db.engine.begin() as conn:
        for name, typ in missing.items():
            conn.execute(text(f"ALTER TABLE card ADD COLUMN {name} {typ}"))


def _ensure_user_columns():
    """Additive, idempotent migration for columns that post-date the original
    `user` table (mirrors `_ensure_card_columns`). Adds the JSON column that
    stores each user's remembered GitHub script-import locations. Safe on every
    boot. NB: ``user`` is a reserved word in Postgres, so quote it."""
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    if "user" not in insp.get_table_names():
        return  # fresh DB: create_all() already built it with every column
    existing = {c["name"] for c in insp.get_columns("user")}
    if "lua_import_sources" in existing:
        return
    with db.engine.begin() as conn:
        conn.execute(text('ALTER TABLE "user" ADD COLUMN lua_import_sources JSON'))


def _widen_text_columns():
    """Lift VARCHAR length caps on free-text columns (currently the per-card
    article caption) for engines that enforce them. Postgres enforces
    VARCHAR(n); SQLite ignores it, so this is a no-op there. Idempotent."""
    if db.engine.dialect.name != "postgresql":
        return
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    targets = {"article_card": ["caption"]}
    with db.engine.begin() as conn:
        for table, cols in targets.items():
            if table not in insp.get_table_names():
                continue
            types = {c["name"]: str(c["type"]).upper()
                     for c in insp.get_columns(table)}
            for col in cols:
                if col in types and "TEXT" not in types[col]:
                    conn.execute(
                        text(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE TEXT"))


def _ensure_moderation_columns():
    """Additive, idempotent migration adding the takedown columns (is_hidden,
    hidden_at, hidden_by_id) to the pre-existing `card` and `article` tables.
    New rows get the model default; existing rows are backfilled to visible.
    Safe on every boot (mirrors `_ensure_card_columns`)."""
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    cols = {"is_hidden": "BOOLEAN", "hidden_at": "TIMESTAMP", "hidden_by_id": "INTEGER"}
    for table in ("card", "article"):
        if table not in insp.get_table_names():
            continue  # fresh DB: create_all() already built it with every column
        existing = {c["name"] for c in insp.get_columns(table)}
        missing = {n: t for n, t in cols.items() if n not in existing}
        if not missing:
            continue
        with db.engine.begin() as conn:
            for name, typ in missing.items():
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {name} {typ}'))
            if "is_hidden" in missing:
                # NOT NULL in the model; backfill so existing rows are visible.
                conn.execute(
                    text(f'UPDATE "{table}" SET is_hidden = :f WHERE is_hidden IS NULL'),
                    {"f": False})


def _bootstrap_admin_from_env(app):
    """Create the first admin from env vars, only if no admin exists yet.
    Lets you bootstrap on hosts with no shell (Render free tier). Safe to
    leave in place: it no-ops once any admin exists."""
    import os
    username = (os.environ.get("BOOTSTRAP_ADMIN_USERNAME") or "").strip()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD") or ""
    if not username or not password:
        return
    from models import User, UserRole
    if User.query.filter_by(role=UserRole.ADMIN).first():
        return  # an admin already exists; never auto-create another
    if User.query.filter(db.func.lower(User.username) == username.lower()).first():
        return  # name taken; skip rather than crash
    user = User(username=username, role=UserRole.ADMIN)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    app.logger.info("Bootstrapped initial admin %r from environment.", username)


def _init_sentry(app):
    """Wire up Sentry error monitoring when SENTRY_DSN is set and sentry-sdk is
    installed. A no-op otherwise, so the dependency stays optional."""
    dsn = (app.config.get("SENTRY_DSN") or "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
    except ImportError:
        app.logger.warning(
            "SENTRY_DSN is set but sentry-sdk isn't installed "
            "(pip install sentry-sdk); error monitoring is disabled.")
        return
    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.0,     # errors only by default; opt into tracing later
        send_default_pii=False,     # don't ship user data to Sentry
    )


def _warn_ephemeral_uploads(app):
    """Warn when the local upload backend is used in a non-dev deploy WITHOUT a
    persistent disk: on a default Render service the local filesystem is
    ephemeral, so those images are lost on every restart/redeploy. Silenced by
    UPLOADS_ON_PERSISTENT_DISK=1 for services that mount a durable disk over the
    uploads directory (in which case local storage is perfectly durable)."""
    if (app.config.get("UPLOAD_BACKEND", "local") == "local"
            and not app.config.get("UPLOADS_ON_PERSISTENT_DISK")
            and os.environ.get("FLASK_DEBUG") != "1"):
        app.logger.warning(
            "UPLOAD_BACKEND=local in a non-debug deploy: on an ephemeral "
            "filesystem uploaded images are LOST on every restart/redeploy. If "
            "you mount a persistent disk over the uploads directory, set "
            "UPLOADS_ON_PERSISTENT_DISK=1 to silence this; otherwise use "
            "UPLOAD_BACKEND=s3 with the S3_* env vars for durable storage.")


def create_app(config_class=Config):
    """Build, configure, and return a Flask application instance."""

    app = Flask(__name__)
    app.config.from_object(config_class)

    _init_sentry(app)             # error monitoring (optional; no-op without DSN)

    # Render (and most PaaS) put the app behind a reverse proxy. Trust one hop of
    # X-Forwarded-* so request.remote_addr is the real client (for rate limiting)
    # and request.is_secure reflects the original HTTPS request (for HSTS).
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Fail safe: the default SECRET_KEY is permitted ONLY when explicitly in
    # local dev (FLASK_DEBUG=1). An unset FLASK_DEBUG now counts as production,
    # so a forgotten env var refuses to boot instead of silently shipping a
    # well-known key (which would let anyone forge a session and become admin).
    if (app.config["SECRET_KEY"] == "dev-only-change-me"
            and os.environ.get("FLASK_DEBUG") != "1"):
        raise RuntimeError(
            "Refusing to start with the default SECRET_KEY. Set the SECRET_KEY "
            "environment variable (or FLASK_DEBUG=1 for local development)."
        )

    # Make SITE_NAME / SITE_TAGLINE available to every template without passing
    # them through each render_template call.
    @app.context_processor
    def inject_site():
        from datetime import datetime
        return {
            "SITE_NAME": app.config["SITE_NAME"],
            "SITE_TAGLINE": app.config["SITE_TAGLINE"],
            "SITE_CONTACT_EMAIL": app.config.get("SITE_CONTACT_EMAIL", ""),
            "now_year": datetime.utcnow().year,
        }

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    _warn_ephemeral_uploads(app)  # flag data-losing local uploads in production

    # --- Security headers + per-request CSP nonce ----------------------------
    # A fresh nonce each request lets us run a strict script-src (no
    # 'unsafe-inline') while still allowing our two tiny inline redirect
    # scripts, which carry nonce="{{ csp_nonce }}".
    @app.before_request
    def _csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def _inject_nonce():
        return {"csp_nonce": g.get("csp_nonce", "")}

    @app.after_request
    def _security_headers(response):
        nonce = g.get("csp_nonce", "")
        csp = (
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            # Cards may link external https art, and JS previews use data:/blob:.
            "img-src 'self' data: blob: https:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        # Only assert HSTS once we know the request actually arrived over HTTPS,
        # so local http development isn't pinned to https.
        from flask import request
        if request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    # Import models so their tables are registered before db.create_all().
    from models import (  # noqa: F401
        User, CardSet, Card, Article, ArticleCard, ArticleSection, Comment,
        UserRole, Report, ReportStatus,
    )

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # --- Register blueprints -------------------------------------------------
    from blueprints.main import main_bp
    from blueprints.articles import articles_bp
    from blueprints.cards import cards_bp
    from blueprints.cdb import cdb_bp
    from blueprints.ypk import ypk_bp
    from blueprints.sets import sets_bp
    from blueprints.auth import auth_bp
    from blueprints.github import github_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(main_bp)

    from blueprints.admin import admin_bp
    app.register_blueprint(admin_bp, url_prefix="/admin")

    from cli import register_cli
    register_cli(app)
    app.register_blueprint(articles_bp, url_prefix="/articles")
    app.register_blueprint(cards_bp, url_prefix="/cards")
    app.register_blueprint(cdb_bp, url_prefix="/cdb")
    app.register_blueprint(ypk_bp, url_prefix="/ypk")
    app.register_blueprint(sets_bp, url_prefix="/sets")
    app.register_blueprint(github_bp, url_prefix="/github")

    from blueprints.moderation import moderation_bp
    app.register_blueprint(moderation_bp, url_prefix="/moderation")

    # Split an effect string on its leading circled markers (①②…⑳, ⓪) so each
    # numbered effect can be rendered in its own little block.
    import re as _re
    _CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳⓪"

    @app.template_filter("effect_parts")
    def _effect_parts(text):
        if not text:
            return []
        out = []
        for chunk in _re.split(r"(?=[\u2460-\u2473\u24ea])", text):
            chunk = chunk.strip()
            if not chunk:
                continue
            if chunk[0] in _CIRCLED:
                out.append({"marker": chunk[0],
                            "text": chunk[1:].strip().lstrip(":").strip()})
            else:
                out.append({"marker": "", "text": chunk})
        return out

    # --- Error handlers ------------------------------------------------------
    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def page_not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(429)
    def too_many_requests(error):
        return render_template("errors/429.html"), 429

    @app.errorhandler(500)
    def server_error(error):
        return render_template("errors/500.html"), 500

    with app.app_context():
        db.create_all()
        _ensure_card_columns()   # add post-hoc columns on existing databases
        _ensure_user_columns()   # add post-hoc columns to the user table
        _ensure_moderation_columns()  # add takedown columns to card + article
        _widen_text_columns()    # drop legacy length caps on free-text columns
        # Populate sample content on first run so the homepage isn't empty.
        # Only seeds an empty DB, and only when SEED_DEMO_DATA is enabled.
        if app.config.get("SEED_DEMO_DATA", True):
            from seed import seed_if_empty
            seed_if_empty()
            _bootstrap_admin_from_env(app)

    return app


if __name__ == "__main__":
    app = create_app()
    # debug=True gives auto-reload and in-browser tracebacks. Never in prod.
    app.run(debug=True)