# path: app.py
"""Entry point. Defines the application factory `create_app()`.

A factory lets you build multiple app instances with different configs
(essential for testing) and keeps top-level code free of side effects.
"""

from flask import Flask, render_template

from config import Config
from extensions import db, login_manager, csrf

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
    wanted = {"cdb_id": "INTEGER", "setcodes": "JSON", "strings": "JSON"}
    missing = {name: typ for name, typ in wanted.items() if name not in existing}
    if not missing:
        return
    with db.engine.begin() as conn:
        for name, typ in missing.items():
            conn.execute(text(f"ALTER TABLE card ADD COLUMN {name} {typ}"))


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


def create_app(config_class=Config):
    """Build, configure, and return a Flask application instance."""

    app = Flask(__name__)
    app.config.from_object(config_class)

    import os
    if (os.environ.get("FLASK_DEBUG", "1") != "1"
            and app.config["SECRET_KEY"] == "dev-only-change-me"):
        raise RuntimeError(
            "Refusing to start outside dev with the default SECRET_KEY. "
            "Set the SECRET_KEY environment variable."
        )

    # Make SITE_NAME / SITE_TAGLINE available to every template without passing
    # them through each render_template call.
    @app.context_processor
    def inject_site():
        from datetime import datetime
        return {
            "SITE_NAME": app.config["SITE_NAME"],
            "SITE_TAGLINE": app.config["SITE_TAGLINE"],
            "now_year": datetime.utcnow().year,
        }

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Import models so their tables are registered before db.create_all().
    from models import (  # noqa: F401
        User, CardSet, Card, Article, ArticleCard, ArticleSection, Comment,
        UserRole,
    )

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # --- Register blueprints -------------------------------------------------
    from blueprints.main import main_bp
    from blueprints.articles import articles_bp
    from blueprints.cards import cards_bp
    from blueprints.cdb import cdb_bp
    from blueprints.sets import sets_bp
    from blueprints.auth import auth_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(main_bp)

    from blueprints.admin import admin_bp
    app.register_blueprint(admin_bp, url_prefix="/admin")

    from cli import register_cli
    register_cli(app)
    app.register_blueprint(articles_bp, url_prefix="/articles")
    app.register_blueprint(cards_bp, url_prefix="/cards")
    app.register_blueprint(cdb_bp, url_prefix="/cdb")
    app.register_blueprint(sets_bp, url_prefix="/sets")

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

    @app.errorhandler(500)
    def server_error(error):
        return render_template("errors/500.html"), 500

    with app.app_context():
        db.create_all()
        _ensure_card_columns()   # add post-hoc columns on existing databases
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