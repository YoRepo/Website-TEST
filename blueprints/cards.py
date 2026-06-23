# path: blueprints/cards.py
"""The 'cards' blueprint: list, create, edit, and delete structured Cards.

A single form template (cards/form.html) serves both create and edit. The POST
handler NORMALISES by category: it reads only the fields relevant to the chosen
card category and explicitly clears the rest, so a Spell can never keep a stale
ATK left in the DOM, etc. JavaScript (static/js/card_form.js) only hides/shows
fields for convenience — the server is the source of truth.
"""

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required

from extensions import db
from blueprints.auth import owner_or_admin
from storage import save_upload, UploadError
from models import (
    Card, CardSet, ArticleCard,
    CardCategory, Attribute, Race, MonsterSummonType, MonsterAbility,
    SpellTrapType, LINK_ARROW_CODES,
)

cards_bp = Blueprint("cards", __name__)

# Real TCG card proportions — must match the display boxes in style.css
# (aspect-ratio: 59 / 86) and the CardSVG canvas (590×860).
CARD_ASPECT = (59, 86)

_EXTRA_DECK = {MonsterSummonType.FUSION, MonsterSummonType.SYNCHRO,
               MonsterSummonType.XYZ, MonsterSummonType.LINK}

# Subtype menus, split per category so each section is self-contained.
SPELL_SUBTYPES = [SpellTrapType.NORMAL, SpellTrapType.FIELD,
                  SpellTrapType.CONTINUOUS, SpellTrapType.QUICK_PLAY,
                  SpellTrapType.RITUAL, SpellTrapType.EQUIP]
TRAP_SUBTYPES = [SpellTrapType.NORMAL, SpellTrapType.CONTINUOUS,
                 SpellTrapType.COUNTER]


# --------------------------------------------------------------------- helpers
def _enum_context():
    """Choice lists handed to the template for building <select>s."""
    return dict(
        categories=list(CardCategory),
        attributes=list(Attribute),
        races=list(Race),
        summon_types=list(MonsterSummonType),
        abilities=list(MonsterAbility),
        spell_subtypes=SPELL_SUBTYPES,
        trap_subtypes=TRAP_SUBTYPES,
        link_codes=LINK_ARROW_CODES,
        sets=CardSet.query.order_by(CardSet.name).all(),
    )


def _int_or_none(raw):
    raw = (raw or "").strip()
    return int(raw) if raw != "" else None   # int() raises ValueError on junk


def _enum_or_none(enum_cls, raw):
    raw = (raw or "").strip()
    return enum_cls[raw] if raw else None     # KeyError on a bad name


def _clean(raw):
    raw = (raw or "").strip()
    return raw or None

def _image_field(name, form, crop_aspect=None):
    """Prefer a newly uploaded file; otherwise keep the text path/URL.
    Clearing the text box with no file removes the image.
    `crop_aspect` (w, h) center-crops a newly uploaded file on the way in."""
    file = request.files.get(f"{name}_file")
    if file and file.filename:
        try:
            return save_upload(file, crop_aspect=crop_aspect)
        except UploadError as exc:
            raise ValueError(str(exc))   # surfaces via the existing flash() path
    return _clean(form.get(name))

def _apply_form(card, form):
    """Populate `card` from submitted `form`, normalised by category.
    Raises ValueError/KeyError on bad input (caught by the caller)."""
    card.name = (form.get("name") or "").strip()
    if not card.name:
        raise ValueError("Name is required.")
    card.category = CardCategory[form["category"]]

    # Inline "create a new set" wins over the dropdown when filled.
    new_set_name = (form.get("new_set_name") or "").strip()
    if new_set_name:
        new_set = CardSet(name=new_set_name, code=_clean(form.get("new_set_code")))
        db.session.add(new_set)
        db.session.flush()  # assign new_set.id
        card.set_id = new_set.id
    else:
        set_id = (form.get("set_id") or "").strip()
        card.set_id = int(set_id) if set_id else None

    card.art_image = _image_field("art_image", form)
    # Render images display in 59:86 card boxes (object-fit: cover); crop the
    # uploaded file to match so margins are gone from the file too, not just
    # clipped at display time. See CARD_ASPECT.
    card.render_image = _image_field("render_image", form, crop_aspect=CARD_ASPECT)

    if card.category == CardCategory.MONSTER:
        card.is_effect = "is_effect" in form
        card.is_pendulum = "is_pendulum" in form
        card.is_tuner = "is_tuner" in form
        card.summon_type = _enum_or_none(MonsterSummonType, form.get("summon_type"))
        card.ability = _enum_or_none(MonsterAbility, form.get("ability"))
        card.attribute = _enum_or_none(Attribute, form.get("attribute"))
        card.race = _enum_or_none(Race, form.get("race"))
        card.level = _int_or_none(form.get("level"))
        card.atk = _int_or_none(form.get("atk"))

        if card.summon_type == MonsterSummonType.LINK:
            card.def_ = None  # Links have no DEF
            card.link_arrows = form.getlist("link_arrows") or None
            card.level = None  # rating is derived from arrows, never stored
        else:
            card.def_ = _int_or_none(form.get("def_"))
            card.link_arrows = None

        if card.is_pendulum:
            card.pendulum_scale = _int_or_none(form.get("pendulum_scale"))
            card.effect_conditions = _clean(form.get("effect_conditions"))
            card.effect_text = _clean(form.get("effect_text"))
        else:
            card.pendulum_scale = None
            card.effect_conditions = None
            card.effect_text = None

        is_extra = card.summon_type in _EXTRA_DECK
        card.materials = _clean(form.get("materials")) if is_extra else None
        card.monster_conditions = _clean(form.get("monster_conditions"))
        card.monster_effect = _clean(form.get("monster_effect"))
        card.spell_trap_type = None
    else:
        # Spell or Trap: one text box, no monster data. Each category has its
        # own subtype field in the form (spell_subtype / trap_subtype).
        if card.category == CardCategory.SPELL:
            card.spell_trap_type = _enum_or_none(SpellTrapType, form.get("spell_subtype"))
        else:
            card.spell_trap_type = _enum_or_none(SpellTrapType, form.get("trap_subtype"))
        card.effect_conditions = _clean(form.get("effect_conditions"))
        card.effect_text = _clean(form.get("effect_text"))
        card.is_effect = card.is_pendulum = card.is_tuner = False
        card.summon_type = card.ability = card.attribute = card.race = None
        card.level = card.pendulum_scale = card.atk = card.def_ = None
        card.link_arrows = None
        card.materials = card.monster_conditions = card.monster_effect = None
    return card


def _formdata_from_card(card):
    """Uniform dict of string-ish values the template reads from (GET path)."""
    return {
        "name": card.name or "",
        "category": card.category.name if card.category else "MONSTER",
        "set_id": str(card.set_id) if card.set_id else "",
        "art_image": card.art_image or "",
        "render_image": card.render_image or "",
        "is_effect": bool(card.is_effect),
        "is_pendulum": bool(card.is_pendulum),
        "is_tuner": bool(card.is_tuner),
        "summon_type": card.summon_type.name if card.summon_type else "",
        "ability": card.ability.name if card.ability else "",
        "attribute": card.attribute.name if card.attribute else "",
        "race": card.race.name if card.race else "",
        "level": card.level if card.level is not None else "",
        "pendulum_scale": card.pendulum_scale if card.pendulum_scale is not None else "",
        "atk": card.atk if card.atk is not None else "",
        "def_": card.def_ if card.def_ is not None else "",
        "arrows": card.link_arrows or [],
        "spell_subtype": card.spell_trap_type.name if (card.is_spell and card.spell_trap_type) else "",
        "trap_subtype": card.spell_trap_type.name if (card.is_trap and card.spell_trap_type) else "",
        "effect_conditions": card.effect_conditions or "",
        "effect_text": card.effect_text or "",
        "materials": card.materials or "",
        "monster_conditions": card.monster_conditions or "",
        "monster_effect": card.monster_effect or "",
    }


_SCALAR_KEYS = ["name", "category", "set_id", "art_image", "render_image",
                "summon_type", "ability", "attribute", "race", "level", "pendulum_scale",
                "atk", "def_", "spell_subtype", "trap_subtype", "effect_conditions",
                "effect_text", "materials", "monster_conditions", "monster_effect"]


def _formdata_from_request(form):
    """Same shape as above but from a failed POST, so input isn't lost."""
    d = {k: form.get(k, "") for k in _SCALAR_KEYS}
    d["is_effect"] = "is_effect" in form
    d["is_pendulum"] = "is_pendulum" in form
    d["is_tuner"] = "is_tuner" in form
    d["arrows"] = form.getlist("link_arrows")
    return d


# ---------------------------------------------------------------------- routes
@cards_bp.route("/")
def list_cards():
    cards = Card.query.order_by(Card.created_at.desc()).all()
    return render_template("cards/list.html", cards=cards)


@cards_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        card = Card()
        try:
            _apply_form(card, request.form)
            card.owner_id = current_user.id
            db.session.add(card)
            db.session.commit()
            flash(f"Created “{card.name}”.", "success")
            return redirect(url_for("cards.edit", card_id=card.id))
        except (ValueError, KeyError) as exc:
            db.session.rollback()
            flash(f"Couldn't save: {exc}", "error")
            return render_template("cards/form.html", mode="new",
                                   data=_formdata_from_request(request.form),
                                   **_enum_context())
    blank = Card(category=CardCategory.MONSTER)
    return render_template("cards/form.html", mode="new",
                           data=_formdata_from_card(blank), **_enum_context())


@cards_bp.route("/<int:card_id>/edit", methods=["GET", "POST"])
@login_required
def edit(card_id):
    card = Card.query.get_or_404(card_id)
    owner_or_admin(card.owner_id)
    if request.method == "POST":
        try:
            _apply_form(card, request.form)
            db.session.commit()
            flash(f"Saved “{card.name}”.", "success")
            return redirect(url_for("cards.edit", card_id=card.id))
        except (ValueError, KeyError) as exc:
            db.session.rollback()
            flash(f"Couldn't save: {exc}", "error")
            return render_template("cards/form.html", mode="edit", card=card,
                                   data=_formdata_from_request(request.form),
                                   **_enum_context())
    return render_template("cards/form.html", mode="edit", card=card,
                           data=_formdata_from_card(card), **_enum_context())


@cards_bp.route("/<int:card_id>/delete", methods=["POST"])
@login_required
def delete(card_id):
    card = Card.query.get_or_404(card_id)
    owner_or_admin(card.owner_id)
    used = ArticleCard.query.filter_by(card_id=card.id).count()
    if used:
        flash(f"“{card.name}” is featured in {used} article(s); "
              "remove it from those first.", "error")
        return redirect(url_for("cards.edit", card_id=card.id))
    name = card.name
    db.session.delete(card)
    db.session.commit()
    flash(f"Deleted “{name}”.", "success")
    return redirect(url_for("cards.list_cards"))