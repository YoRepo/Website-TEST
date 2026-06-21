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
    CDB_MAX_SETCODES, CDB_DEFAULT_STRING_COUNT, default_card_strings,
)

cards_bp = Blueprint("cards", __name__)

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


def _parse_cdb_id(form, card):
    """The card's .cdb passcode: optional, positive, and unique across cards so
    two cards can never collide in a generated database."""
    raw = (form.get("cdb_id") or "").strip()
    if not raw:
        return None
    try:
        val = int(raw)
    except ValueError:
        raise ValueError("Card ID must be a whole number.")
    if val <= 0:
        raise ValueError("Card ID must be a positive number.")
    clash = Card.query.filter(Card.cdb_id == val, Card.id != card.id).first()
    if clash:
        raise ValueError(f"Card ID {val} is already used by “{clash.name}”.")
    return val


def _parse_script(form):
    """The card's Lua script. Preserve indentation exactly; only normalise line
    endings and trim surrounding blank lines. Empty → NULL."""
    raw = (form.get("script") or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = raw.strip("\n")
    return raw or None


def _parse_setcodes(form):
    """Read the up-to-four set-code boxes into a list of ints. Codes are
    hexadecimal archetype ids (e.g. 0x103); a bare '103' is read as hex too,
    matching how archetypes are conventionally written. Returns None if empty."""
    out = []
    for i in range(CDB_MAX_SETCODES):
        raw = (form.get(f"setcode_{i}") or "").strip().lower()
        if raw.startswith("0x"):
            raw = raw[2:]
        if not raw:
            continue
        try:
            val = int(raw, 16)
        except ValueError:
            raise ValueError(
                f"Set code “{form.get(f'setcode_{i}')}” must be hexadecimal "
                "(e.g. 0x103).")
        if not (0 < val <= 0xFFFF):
            raise ValueError("Each set code must be between 0x1 and 0xFFFF.")
        out.append(val)
    return out or None


def _parse_strings(form):
    """Read the nine card-string boxes into a stable-length list (kept even when
    blank so string ids stay aligned to their positions)."""
    return [(form.get(f"string_{i}") or "").strip()
            for i in range(CDB_DEFAULT_STRING_COUNT)]

def _image_field(name, form):
    """Prefer a newly uploaded file; otherwise keep the text path/URL.
    Clearing the text box with no file removes the image."""
    file = request.files.get(f"{name}_file")
    if file and file.filename:
        try:
            return save_upload(file)
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
    card.render_image = _image_field("render_image", form)

    # EDOPro export metadata — independent of card category.
    card.cdb_id = _parse_cdb_id(form, card)
    card.setcodes = _parse_setcodes(form)
    card.strings = _parse_strings(form)
    card.script = _parse_script(form)

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
        card.is_trap_monster = False
    else:
        # Spell or Trap: one text box. Each category has its own subtype field
        # in the form (spell_subtype / trap_subtype).
        if card.category == CardCategory.SPELL:
            card.spell_trap_type = _enum_or_none(SpellTrapType, form.get("spell_subtype"))
            card.is_trap_monster = False
        else:
            card.spell_trap_type = _enum_or_none(SpellTrapType, form.get("trap_subtype"))
            card.is_trap_monster = "is_trap_monster" in form
        card.effect_conditions = _clean(form.get("effect_conditions"))
        card.effect_text = _clean(form.get("effect_text"))
        card.is_effect = card.is_pendulum = card.is_tuner = False
        card.summon_type = card.ability = None
        card.pendulum_scale = None
        card.link_arrows = None
        card.materials = card.monster_conditions = card.monster_effect = None

        # A Trap Monster reuses the monster-stat columns; a plain Spell/Trap
        # clears them.
        if card.category == CardCategory.TRAP and card.is_trap_monster:
            card.attribute = _enum_or_none(Attribute, form.get("tm_attribute"))
            card.race = _enum_or_none(Race, form.get("tm_race"))
            card.level = _int_or_none(form.get("tm_level"))
            card.atk = _int_or_none(form.get("tm_atk"))
            card.def_ = _int_or_none(form.get("tm_def"))
            card.is_effect = "tm_is_effect" in form
            card.is_tuner = "tm_is_tuner" in form
            card.ability = _enum_or_none(MonsterAbility, form.get("tm_ability"))
        else:
            card.attribute = card.race = None
            card.level = card.atk = card.def_ = None
    return card


def _setcodes_display(setcodes):
    """Pad/clip stored set codes to CDB_MAX_SETCODES hex strings for the form."""
    disp = [(f"0x{int(c):x}" if c else "") for c in (setcodes or [])]
    disp += [""] * CDB_MAX_SETCODES
    return disp[:CDB_MAX_SETCODES]


def _strings_display(strings):
    """Pad/clip to the nine managed strings for the form, defaulting blanks."""
    src = list(strings) if strings else default_card_strings()
    src += [""] * CDB_DEFAULT_STRING_COUNT
    return src[:CDB_DEFAULT_STRING_COUNT]


def _formdata_from_card(card):
    """Uniform dict of string-ish values the template reads from (GET path)."""
    return {
        "cdb_id": card.cdb_id if card.cdb_id is not None else "",
        "setcodes": _setcodes_display(card.setcodes),
        "strings": _strings_display(card.strings),
        "script": card.script or "",
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
        "is_trap_monster": bool(card.is_trap_monster),
        "tm_attribute": card.attribute.name if (card.is_trap_monster and card.attribute) else "",
        "tm_race": card.race.name if (card.is_trap_monster and card.race) else "",
        "tm_level": card.level if (card.is_trap_monster and card.level is not None) else "",
        "tm_atk": card.atk if (card.is_trap_monster and card.atk is not None) else "",
        "tm_def": card.def_ if (card.is_trap_monster and card.def_ is not None) else "",
        "tm_is_effect": bool(card.is_trap_monster and card.is_effect),
        "tm_is_tuner": bool(card.is_trap_monster and card.is_tuner),
        "tm_ability": card.ability.name if (card.is_trap_monster and card.ability) else "",
        "effect_conditions": card.effect_conditions or "",
        "effect_text": card.effect_text or "",
        "materials": card.materials or "",
        "monster_conditions": card.monster_conditions or "",
        "monster_effect": card.monster_effect or "",
    }


_SCALAR_KEYS = ["name", "category", "set_id", "art_image", "render_image", "cdb_id",
                "script",
                "summon_type", "ability", "attribute", "race", "level", "pendulum_scale",
                "atk", "def_", "spell_subtype", "trap_subtype", "effect_conditions",
                "effect_text", "materials", "monster_conditions", "monster_effect",
                "tm_attribute", "tm_race", "tm_level", "tm_atk", "tm_def", "tm_ability"]


def _formdata_from_request(form):
    """Same shape as above but from a failed POST, so input isn't lost."""
    d = {k: form.get(k, "") for k in _SCALAR_KEYS}
    d["is_effect"] = "is_effect" in form
    d["is_pendulum"] = "is_pendulum" in form
    d["is_tuner"] = "is_tuner" in form
    d["is_trap_monster"] = "is_trap_monster" in form
    d["tm_is_effect"] = "tm_is_effect" in form
    d["tm_is_tuner"] = "tm_is_tuner" in form
    d["arrows"] = form.getlist("link_arrows")
    d["setcodes"] = [form.get(f"setcode_{i}", "") for i in range(CDB_MAX_SETCODES)]
    d["strings"] = [form.get(f"string_{i}", "") for i in range(CDB_DEFAULT_STRING_COUNT)]
    return d


def _taken_cdb_ids(exclude_id=None):
    """Map of {cdb_id (str): card name} already in use, for inline duplicate
    flagging in the editor. Excludes the card being edited."""
    q = Card.query.filter(Card.cdb_id.isnot(None))
    if exclude_id is not None:
        q = q.filter(Card.id != exclude_id)
    return {str(c.cdb_id): c.name for c in q.all()}


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
                                   taken_cdb_ids=_taken_cdb_ids(),
                                   **_enum_context())
    blank = Card(category=CardCategory.MONSTER)
    return render_template("cards/form.html", mode="new",
                           data=_formdata_from_card(blank),
                           taken_cdb_ids=_taken_cdb_ids(), **_enum_context())


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
                                   taken_cdb_ids=_taken_cdb_ids(card.id),
                                   **_enum_context())
    return render_template("cards/form.html", mode="edit", card=card,
                           data=_formdata_from_card(card),
                           taken_cdb_ids=_taken_cdb_ids(card.id), **_enum_context())


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