# path: blueprints/ypk.py
"""The 'ypk' blueprint: build a downloadable, game-ready ``.ypk`` custom card
pack from a set of existing Cards.

The editor (templates/ypk/form.html + static/js/ypk_form.js) is the card picker
you already know: a pack name, then cards chosen with the visual picker. Each
card brings its own Card ID, Lua script, and render image (all configured in
the card editor), so there's nothing to type per card. On submit this handler
maps the cards into a .cdb, bundles their scripts (script/c<id>.lua) and images
(pics/<id>.<ext>) around it, and streams the finished .ypk (see ypk_export.py).
"""

import json
import os
import re
import tempfile

from flask import (
    Blueprint, after_this_request, flash, render_template, request, send_file,
)
from flask_login import login_required

from ypk_export import build_ypk
from models import Card

ypk_bp = Blueprint("ypk", __name__)


def _cards_for_picker():
    """Picker payload + flags showing what each card will contribute to a pack
    (so the user can spot a missing script or render before generating)."""
    return [{"id": c.id, "name": c.name, "type_line": c.type_line,
             "set": c.card_set.name if c.card_set else "",
             "cdb_id": c.cdb_id if c.cdb_id is not None else "",
             "has_script": bool(c.script and c.script.strip()),
             "has_image": bool(c.render_image),
             "render_image": c.render_image or "",
             "svg_state": c.svg_state}
            for c in Card.query.filter(Card.is_hidden.is_(False))
                               .order_by(Card.name).all()]


def _safe_pack_name(raw):
    base = (raw or "").strip()
    base = re.sub(r"\.ypk$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")
    return base or "custom-cards"


def _parse_items(structure):
    """Validate editor JSON into ``(cdb_id, Card)`` pairs, resolving each id from
    the builder override or the card's stored Card ID. Raises ValueError with a
    user-facing message on any problem."""
    cards = structure.get("cards") or []
    if not cards:
        raise ValueError("Add at least one card before generating a .ypk.")

    items, seen = [], set()
    for entry in cards:
        card = Card.query.get(entry.get("card_id"))
        if card is None:
            raise ValueError("A selected card no longer exists; remove it.")
        if card.is_hidden:
            raise ValueError(f"“{card.name}” has been removed by a moderator; "
                             "remove it from this build.")

        raw_id = str(entry.get("cdb_id", "")).strip()
        if not raw_id and card.cdb_id is not None:
            raw_id = str(card.cdb_id)
        if not raw_id:
            raise ValueError(
                f"“{card.name}” has no Card ID — set one in the card editor.")
        try:
            cdb_id = int(raw_id)
        except ValueError:
            raise ValueError(f"Card id “{raw_id}” must be a whole number.")
        if cdb_id <= 0:
            raise ValueError(f"Card id {cdb_id} must be a positive number.")
        if cdb_id in seen:
            raise ValueError(f"Card id {cdb_id} is used more than once.")
        seen.add(cdb_id)
        items.append((cdb_id, card))
    return items


def _safe_structure(raw):
    try:
        return json.loads(raw or '{"cards": []}')
    except json.JSONDecodeError:
        return {"cards": []}


@ypk_bp.route("/new", methods=["GET"])
@login_required
def new():
    return render_template("ypk/form.html", cards=_cards_for_picker(),
                           form={}, structure_obj={"cards": []})


@ypk_bp.route("/generate", methods=["POST"])
@login_required
def generate():
    pack_name = _safe_pack_name(request.form.get("filename"))
    try:
        structure = json.loads(request.form.get("structure") or '{"cards": []}')
        items = _parse_items(structure)
    except (ValueError, json.JSONDecodeError) as exc:
        flash(f"Couldn't generate .ypk: {exc}", "error")
        return render_template(
            "ypk/form.html", cards=_cards_for_picker(),
            form={"filename": request.form.get("filename", "")},
            structure_obj=_safe_structure(request.form.get("structure")))

    fd, path = tempfile.mkstemp(suffix=".ypk")
    os.close(fd)
    try:
        build_ypk(path, pack_name, items)
    except ValueError as exc:
        os.remove(path)
        flash(f"Couldn't generate .ypk: {exc}", "error")
        return render_template(
            "ypk/form.html", cards=_cards_for_picker(),
            form={"filename": request.form.get("filename", "")},
            structure_obj=structure)

    @after_this_request
    def _cleanup(response):
        try:
            os.remove(path)
        except OSError:
            pass
        return response

    return send_file(path, as_attachment=True, download_name=f"{pack_name}.ypk",
                     mimetype="application/zip")
