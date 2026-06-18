# path: blueprints/admin.py
"""Admin-only user management screen."""

from flask import (
    Blueprint, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user

from extensions import db
from models import User, UserRole
from blueprints.auth import admin_required

admin_bp = Blueprint("admin", __name__)


def _active_admin_count():
    return User.query.filter_by(role=UserRole.ADMIN, active=True).count()


@admin_bp.route("/users")
@admin_required
def users():
    people = User.query.order_by(User.username).all()
    return render_template("admin/users.html", people=people, roles=list(UserRole))


@admin_bp.route("/users/<int:user_id>/role", methods=["POST"])
@admin_required
def set_role(user_id):
    user = User.query.get_or_404(user_id)
    try:
        new_role = UserRole[request.form.get("role", "")]
    except KeyError:
        flash("Unknown role.", "error")
        return redirect(url_for("admin.users"))

    if user.id == current_user.id and new_role != UserRole.ADMIN:
        flash("You can't remove your own admin rights.", "error")
        return redirect(url_for("admin.users"))
    if (user.role == UserRole.ADMIN and new_role != UserRole.ADMIN
            and _active_admin_count() <= 1):
        flash("That's the last active admin — promote someone else first.", "error")
        return redirect(url_for("admin.users"))

    user.role = new_role
    db.session.commit()
    flash(f"{user.username} is now {new_role.value}.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/active", methods=["POST"])
@admin_required
def toggle_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You can't disable your own account.", "error")
        return redirect(url_for("admin.users"))
    if (user.active and user.role == UserRole.ADMIN
            and _active_admin_count() <= 1):
        flash("That's the last active admin — can't disable them.", "error")
        return redirect(url_for("admin.users"))
    user.active = not user.active
    db.session.commit()
    flash(f"{user.username} login {'enabled' if user.active else 'disabled'}.", "success")
    return redirect(url_for("admin.users"))