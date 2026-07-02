# path: blueprints/cdb.py
"""The 'cdb' blueprint: build a downloadable EDOPro/YGOPro ``.cdb`` from a set
of existing Cards.

The editor (templates/cdb/form.html + static/js/cdb_form.js) mirrors the
article editor: a filename field replaces the title, the same visual card
picker selects cards, and each picked card carries a *card id* (its passcode in
the generated database) instead of a caption. On submit the chosen structure is
serialised to a hidden JSON field; this handler maps each Card to the cdb
schema (see cdb_export.py) and streams the finished file back as a download.
"""

import json
import os
import re
import tempfile

from flask import (
    Blueprint, after_this_request, flash, render_template, request, send_file,
)
from flask_login import login_required

from cdb_export import build_cdb
from extensions import limiter
from models import Card

cdb_bp = Blueprint("cdb", __name__)

# Throttle .cdb generation (server-side file building). GET is exempt.
_GENERATE_LIMIT = "10 per minute; 60 per hour"


def _cards_for_picker():
    """Same payload the article editor uses, so the shared picker widget and
    SVG fallback render identically here."""
    return [{"id": c.id, "name": c.name, "type_line": c.type_line,
             "set": c.card_set.name if c.card_set else "",
             "cdb_id": c.cdb_id if c.cdb_id is not None else "",
             "render_image": c.render_image or "",
             "svg_state": c.svg_state}
            for c in Card.query.filter(Card.is_hidden.is_(False))
                               .order_by(Card.name).all()]


def _safe_filename(raw):
    """Turn user input into a safe ``*.cdb`` filename."""
    base = (raw or "").strip()
    base = re.sub(r"\.cdb$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")
    return f"{base or 'cards'}.cdb"


def _parse_items(structure):
    """Validate the editor JSON into a list of ``(cdb_id, Card)`` pairs.
    Raises ValueError with a user-facing message on any problem."""
    cards = structure.get("cards") or []
    if not cards:
        raise ValueError("Add at least one card before generating a .cdb.")

    items, seen = [], set()
    for entry in cards:
        card = Card.query.get(entry.get("card_id"))
        if card is None:
            raise ValueError("A selected card no longer exists; remove it.")
        if card.is_hidden:
            raise ValueError(f"“{card.name}” has been removed by a moderator; "
                             "remove it from this build.")

        # Prefer an explicit override typed in the builder; otherwise use the
        # id configured on the card itself in the editor.
        raw_id = str(entry.get("cdb_id", "")).strip()
        if not raw_id and card.cdb_id is not None:
            raw_id = str(card.cdb_id)
        if not raw_id:
            raise ValueError(
                f"“{card.name}” has no Card ID — set one in the card editor "
                "(or type one here).")
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


@cdb_bp.route("/new", methods=["GET"])
@login_required
def new():
    return render_template("cdb/form.html", cards=_cards_for_picker(),
                           form={}, structure_obj={"cards": []})


@cdb_bp.route("/generate", methods=["POST"])
@limiter.limit(_GENERATE_LIMIT)
@login_required
def generate():
    filename = _safe_filename(request.form.get("filename"))
    try:
        structure = json.loads(request.form.get("structure") or '{"cards": []}')
        items = _parse_items(structure)
    except (ValueError, json.JSONDecodeError) as exc:
        flash(f"Couldn't generate .cdb: {exc}", "error")

        def _safe_structure(raw):
            try:
                return json.loads(raw or '{"cards": []}')
            except json.JSONDecodeError:
                return {"cards": []}

        return render_template(
            "cdb/form.html", cards=_cards_for_picker(),
            form={"filename": request.form.get("filename", "")},
            structure_obj=_safe_structure(request.form.get("structure")))

    # Build into a temp file, then stream it and clean up afterwards.
    fd, path = tempfile.mkstemp(suffix=".cdb")
    os.close(fd)
    try:
        build_cdb(path, items)
    except ValueError as exc:
        os.remove(path)
        flash(f"Couldn't generate .cdb: {exc}", "error")
        return render_template(
            "cdb/form.html", cards=_cards_for_picker(),
            form={"filename": request.form.get("filename", "")},
            structure_obj=structure)

    @after_this_request
    def _cleanup(response):
        try:
            os.remove(path)
        except OSError:
            pass
        return response

    return send_file(path, as_attachment=True, download_name=filename,
                     mimetype="application/x-sqlite3")
