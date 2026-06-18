# path: blueprints/sets.py
"""The 'sets' blueprint: list, create, and delete CardSets."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import CardSet
from blueprints.auth import owner_or_admin

sets_bp = Blueprint("sets", __name__)


@sets_bp.route("/")
def list_sets():
    sets = CardSet.query.order_by(CardSet.name).all()
    return render_template("sets/list.html", sets=sets)


@sets_bp.route("/new", methods=["POST"])
@login_required
def new():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Set name is required.", "error")
        return redirect(url_for("sets.list_sets"))
    s = CardSet(
        name=name,
        code=(request.form.get("code") or "").strip() or None,
        description=(request.form.get("description") or "").strip() or None,
        owner_id=current_user.id,
    )
    db.session.add(s)
    db.session.commit()
    flash(f"Created set “{s.name}”.", "success")
    return redirect(url_for("sets.list_sets"))


@sets_bp.route("/<int:set_id>/delete", methods=["POST"])
@login_required
def delete(set_id):
    s = CardSet.query.get_or_404(set_id)
    owner_or_admin(s.owner_id)
    if s.cards:
        flash(f"“{s.name}” still has {len(s.cards)} card(s); reassign them first.",
              "error")
        return redirect(url_for("sets.list_sets"))
    name = s.name
    db.session.delete(s)
    db.session.commit()
    flash(f"Deleted set “{name}”.", "success")
    return redirect(url_for("sets.list_sets"))