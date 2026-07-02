# path: blueprints/auth.py
"""Authentication (register / login / logout) and authorization helpers."""

from functools import wraps
from urllib.parse import urlsplit

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, url_for,
)
from flask_login import (
    current_user, login_required, login_user, logout_user,
)

from extensions import db, limiter
from models import User, UserRole
from security import normalize_redirect_target

auth_bp = Blueprint("auth", __name__)

MIN_PASSWORD_LEN = 10

# Brute-force / abuse throttles, per client IP. GET (showing the form) is exempt
# so only actual submissions count against the limit.
_LOGIN_LIMIT = "10 per minute; 60 per hour"
_REGISTER_LIMIT = "5 per minute; 20 per hour"


def admin_required(view):
    """Admins only. Place directly above the view (it adds login_required)."""
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def staff_required(view):
    """Staff only (moderators + admins). For the moderation queue and takedowns.
    Place directly above the view (it adds login_required)."""
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_staff:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def owner_or_admin(owner_id):
    """403 unless the current user owns the object or is an admin. (Edits.)"""
    if not (current_user.is_admin or owner_id == current_user.id):
        abort(403)


def owner_or_staff(owner_id):
    """403 unless the current user owns the object or is staff. (Deletes.)"""
    if not (current_user.is_staff or owner_id == current_user.id):
        abort(403)


def _safe_next(target):
    """Open-redirect guard: only allow same-site relative paths. Folds
    backslashes first so ``/\\evil.com`` (which browsers read as ``//evil.com``)
    can't slip past the scheme/netloc check."""
    target = normalize_redirect_target(target)
    if not target:
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return None
    return target


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit(_REGISTER_LIMIT, methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        display_name = (request.form.get("display_name") or "").strip() or None
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        accepted = bool(request.form.get("accept_terms"))

        errors = []
        if not (3 <= len(username) <= 40) or not username.isalnum():
            errors.append("Username must be 3–40 letters or digits.")
        if User.query.filter(db.func.lower(User.username) == username.lower()).first():
            errors.append("That username is taken.")
        if len(password) < MIN_PASSWORD_LEN:
            errors.append(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
        if password != confirm:
            errors.append("Passwords don't match.")
        if not accepted:
            errors.append("Please accept the Terms and Acceptable Use Policy.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "auth/register.html",
                form={"username": username, "display_name": display_name or "",
                      "accept_terms": accepted})

        user = User(username=username, display_name=display_name,
                    role=UserRole.USER)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash(f"Welcome, {user.display_name or user.username}!", "success")
        return redirect(url_for("main.index"))
    return render_template("auth/register.html", form={})


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit(_LOGIN_LIMIT, methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        remember = bool(request.form.get("remember"))

        user = User.query.filter(
            db.func.lower(User.username) == username.lower()).first()
        # Generic message: don't reveal whether the username exists.
        if user is None or not user.active or not user.check_password(password):
            flash("Invalid username or password.", "error")
            return render_template("auth/login.html", form={"username": username})

        login_user(user, remember=remember)
        flash(f"Welcome back, {user.display_name or user.username}.", "success")
        return redirect(_safe_next(request.args.get("next")) or url_for("main.index"))
    return render_template("auth/login.html", form={})


@auth_bp.route("/logout", methods=["POST"])   # POST-only: CSRF-safe, crawler-safe
@login_required
def logout():
    logout_user()
    flash("Signed out.", "success")
    return redirect(url_for("main.index"))