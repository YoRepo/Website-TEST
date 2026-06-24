# path: models.py
"""Database models for TheCustomDuelist.

The domain has three top-level entities:

  • User      — owns sets, cards, articles, and comments.
  • CardSet    — a user-curated collection of cards ("their own custom set").
  • Card       — a fully-structured custom card (the heart of the app). All the
                 data needed to render a card image lives here.
  • Article    — a write-up that *features* one or more existing Cards (chosen
                 from the database) via the ArticleCard association.
  • Comment    — a reader comment on an Article.

A note on the Card design
-------------------------
A real TCG card is a classic "type-discriminator with conditional fields"
problem: a Monster has ATK/DEF/Level/Attribute/Race, a Spell/Trap has almost
none of that, and a Pendulum monster has *two* text boxes. Rather than three
separate tables (joined inheritance) we use ONE `card` table with a `category`
discriminator and nullable, category-specific columns. Card effect text is
freeform, the shared columns dominate, and a single table keeps the "let the
user pick any card" queries trivial (one `Card.query`, filter as needed).
Validation of "which fields are required for which category" is light here and
belongs mostly in the form layer; the model enforces only ranges and the
obvious invariants.
"""

import enum
from datetime import datetime
import re

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import validates

from extensions import db


# ===========================================================================
#  ENUMS — the fixed choice lists. Stored by member NAME (e.g. "FIRE").
# ===========================================================================
class CardCategory(enum.Enum):
    """Top-level kind of card — the discriminator that decides which other
    fields are meaningful."""
    MONSTER = "Monster"
    SPELL = "Spell"
    TRAP = "Trap"


class Attribute(enum.Enum):
    """Monster attribute. Spell/Trap cards don't store one — their icon is
    derived from the category (see Card.display_attribute)."""
    EARTH = "EARTH"
    WATER = "WATER"
    FIRE = "FIRE"
    WIND = "WIND"
    LIGHT = "LIGHT"
    DARK = "DARK"
    DIVINE = "DIVINE"


class MonsterSummonType(enum.Enum):
    """The special-summon mechanic / card frame. NULL means a plain main-deck
    monster (Normal or Effect). RITUAL is main-deck; the rest are Extra Deck."""
    RITUAL = "Ritual"
    FUSION = "Fusion"
    SYNCHRO = "Synchro"
    XYZ = "Xyz"
    LINK = "Link"


class MonsterAbility(enum.Enum):
    """The monster "subtype" / ability. At most one in this model."""
    SPIRIT = "Spirit"
    UNION = "Union"
    GEMINI = "Gemini"
    FLIP = "Flip"
    TOON = "Toon"


class Race(enum.Enum):
    """Monster race (the game calls this "Type", but we already use Type for
    other things, so: Race)."""
    WARRIOR = "Warrior"
    SPELLCASTER = "Spellcaster"
    FAIRY = "Fairy"
    FIEND = "Fiend"
    ZOMBIE = "Zombie"
    MACHINE = "Machine"
    AQUA = "Aqua"
    PYRO = "Pyro"
    ROCK = "Rock"
    WINGED_BEAST = "Winged Beast"
    PLANT = "Plant"
    INSECT = "Insect"
    THUNDER = "Thunder"
    DRAGON = "Dragon"
    BEAST = "Beast"
    BEAST_WARRIOR = "Beast-Warrior"
    DINOSAUR = "Dinosaur"
    FISH = "Fish"
    SEA_SERPENT = "Sea-Serpent"
    REPTILE = "Reptile"
    PSYCHIC = "Psychic"
    WYRM = "Wyrm"
    CYBERSE = "Cyberse"
    ILLUSION = "Illusion"
    DIVINE = "Divine"


class SpellTrapType(enum.Enum):
    """Subtype for Spell AND Trap cards (one column, validated against the
    card's category). NORMAL/CONTINUOUS are valid for both."""
    NORMAL = "Normal"
    CONTINUOUS = "Continuous"
    FIELD = "Field"          # Spell only
    QUICK_PLAY = "Quick-Play"  # Spell only
    RITUAL = "Ritual"        # Spell only (a Ritual Spell ≠ a Ritual Monster)
    EQUIP = "Equip"          # Spell only
    COUNTER = "Counter"      # Trap only


# Which SpellTrapType values are legal for each card category.
_SPELL_SUBTYPES = {
    SpellTrapType.NORMAL, SpellTrapType.CONTINUOUS, SpellTrapType.FIELD,
    SpellTrapType.QUICK_PLAY, SpellTrapType.RITUAL, SpellTrapType.EQUIP,
}
_TRAP_SUBTYPES = {
    SpellTrapType.NORMAL, SpellTrapType.CONTINUOUS, SpellTrapType.COUNTER,
}

# Link-arrow position codes (used in Card.link_arrows for Link monsters).
LINK_ARROW_CODES = ("TL", "T", "TR", "L", "R", "BL", "B", "BR")

# The same codes as emoji, for the plaintext "copy card as text" feature.
LINK_ARROW_EMOJI = {
    "TL": "↖️", "T": "⬆️", "TR": "↗️",
    "L": "⬅️", "R": "➡️",
    "BL": "↙️", "B": "⬇️", "BR": "↘️",
}
# Order arrows are listed in for the plaintext export: around the card's
# perimeter, counter-clockwise from the top-left, so e.g. {L, B, R} reads
# ⬅️⬇️➡️ (left, down, right).
LINK_ARROW_PLAINTEXT_ORDER = ("TL", "L", "BL", "B", "BR", "R", "TR", "T")

# Circled effect markers ①..⑳ plus ⓪. A card's effect text strings them
# together; we split on them to show each numbered effect on its own line.
CIRCLED_MARKERS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳⓪"


def split_effect_parts(text):
    """Split effect text into a list of ``{"marker", "text"}`` dicts, breaking
    before each leading circled marker (①, ②, …). Text before the first marker
    (or text with no markers at all) becomes a single markerless part. Shared by
    the on-page renderer (the ``effect_parts`` template filter) and the
    plaintext export (:pyattr:`Card.copy_text`) so they never drift apart."""
    if not text:
        return []
    out = []
    for chunk in re.split(r"(?=[①-⑳⓪])", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk[0] in CIRCLED_MARKERS:
            out.append({"marker": chunk[0],
                        "text": chunk[1:].strip().lstrip(":").strip()})
        else:
            out.append({"marker": "", "text": chunk})
    return out


def _effect_lines(text):
    """Yield each effect part of `text` as one plaintext line: ``marker text``
    (a bare marker when its text is empty, the text alone when unmarked)."""
    for part in split_effect_parts(text):
        if part["marker"]:
            yield f"{part['marker']} {part['text']}".rstrip()
        else:
            yield part["text"]

# --- EDOPro .cdb export limits ---------------------------------------------
# A .cdb packs all set codes into one 64-bit column, 16 bits each → 4 max.
CDB_MAX_SETCODES = 4
# The texts table has str1..str16 (string ids 0..15). We manage the first 9 by
# default; Lua references them via aux.Stringid(code, id) where id → str(id+1).
CDB_MAX_STRINGS = 16
CDB_DEFAULT_STRING_COUNT = 9


def default_card_strings():
    """Nine self-documenting placeholders: string id ``i`` → text ``"string i"``.
    During playtesting an unedited string shows up in-game as e.g. "string 3",
    which is exactly the id you then edit."""
    return [f"string {i}" for i in range(CDB_DEFAULT_STRING_COUNT)]


class UserRole(enum.Enum):
    USER = "User"
    MODERATOR = "Moderator"
    ADMIN = "Admin"

class ArticleStatus(enum.Enum):
    DRAFT = "Draft"
    PUBLISHED = "Published"


# ===========================================================================
#  USER — owner of everything. Minimal stub for now; real auth (password
#  hashing, login) is a later step. Ownership FKs are nullable until then so
#  seeding and anonymous content still work.
# ===========================================================================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False)
    display_name = db.Column(db.String(80), nullable=True)
    email = db.Column(db.String(255), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum(UserRole), nullable=False, default=UserRole.USER)
    # Renamed from Flask-Login's `is_active` so we can store + override it.
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Remembered GitHub locations the user has imported Lua card scripts from,
    # for one-click re-browsing in the card editor. A most-recent-first list of
    # dicts: {owner, repo, ref, path, label, last_used}. See blueprints/github.py.
    lua_import_sources = db.Column(db.JSON, nullable=True, default=list)

    sets = db.relationship("CardSet", backref="owner", lazy="selectin")
    cards = db.relationship("Card", backref="owner", lazy="selectin")
    articles = db.relationship("Article", backref="author", lazy="selectin")
    comments = db.relationship("Comment", backref="author", lazy="selectin")

    # --- auth helpers -----------------------------------------------------
    def set_password(self, password):
        # Werkzeug picks a strong salted hash (scrypt/pbkdf2 per version).
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN

    @property
    def is_staff(self):
        """Moderators and admins — can moderate (take down) any content."""
        return self.role in (UserRole.MODERATOR, UserRole.ADMIN)

    @property
    def is_active(self):           # consulted by Flask-Login on every request
        return self.active

    def __repr__(self):
        return f"<User id={self.id} username={self.username!r}>"


# ===========================================================================
#  CARDSET — a user's custom collection. A Card belongs to at most one set
#  (one-to-many). If you later want reprints (one card in several sets), swap
#  this for a many-to-many association.
# ===========================================================================
class CardSet(db.Model):
    # NB: named CardSet, not Set — `set` is a Python builtin.
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(12), nullable=True)   # e.g. a short set prefix
    description = db.Column(db.String(280), nullable=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    cards = db.relationship(
        "Card",
        backref="card_set",
        order_by="Card.created_at",
        lazy="selectin",
    )

    @property
    def card_count(self):
        return len(self.cards)

    def __repr__(self):
        return f"<CardSet id={self.id} name={self.name!r}>"


# ===========================================================================
#  CARD — the structured custom card.
# ===========================================================================
class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    # --- Common -----------------------------------------------------------
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.Enum(CardCategory), nullable=False)

    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    set_id = db.Column(db.Integer, db.ForeignKey("card_set.id"), nullable=True)

    # Images: `art_image` is the square artwork that goes INSIDE the frame;
    # `render_image` is the finished, generated card. Both are paths (relative
    # to static/, or an upload URL later) and are NULL until generated.
    art_image = db.Column(db.String(255), nullable=True)
    render_image = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # --- Monster-only -----------------------------------------------------
    is_effect = db.Column(db.Boolean, nullable=False, default=False)
    is_pendulum = db.Column(db.Boolean, nullable=False, default=False)
    is_tuner = db.Column(db.Boolean, nullable=False, default=False)
    summon_type = db.Column(db.Enum(MonsterSummonType), nullable=True)
    ability = db.Column(db.Enum(MonsterAbility), nullable=True)
    attribute = db.Column(db.Enum(Attribute), nullable=True)
    race = db.Column(db.Enum(Race), nullable=True)
    # One column serves Level / Rank / Link-Rating (see level_label).
    level = db.Column(db.Integer, nullable=True)        # 0–13
    pendulum_scale = db.Column(db.Integer, nullable=True)  # 0–13, pendulum only
    atk = db.Column(db.Integer, nullable=True)
    def_ = db.Column("def", db.Integer, nullable=True)  # NULL for Link monsters
    # Link monsters only: list of arrow codes from LINK_ARROW_CODES.
    link_arrows = db.Column(db.JSON, nullable=True)

    # --- Spell/Trap-only --------------------------------------------------
    spell_trap_type = db.Column(db.Enum(SpellTrapType), nullable=True)
    # A Trap card that Special Summons itself as a monster (e.g. Embodiment of
    # Apophis). When true, the monster-stat columns above (attribute / race /
    # level / atk / def_) are reused to hold the stats it gains once Summoned.
    # In the .cdb these are written to the data row while the type stays a plain
    # Trap — matching how the game's own database encodes trap monsters.
    is_trap_monster = db.Column(db.Boolean, nullable=False, default=False)

    # --- EDOPro .cdb export metadata (not used by the on-site renderer) ----
    # The passcode this card gets in a generated .cdb (its `datas.id`). Chosen
    # once here so the .cdb builder never has to ask. Use a high custom range
    # (e.g. 100000001+) to avoid clashing with real Konami card ids.
    cdb_id = db.Column(db.Integer, nullable=True)
    # Up to CDB_MAX_SETCODES archetype codes (ints), packed into the cdb's
    # 64-bit `setcode` column on export.
    setcodes = db.Column(db.JSON, nullable=True)
    # In-game card strings (texts.str1..str16). Defaults to nine self-
    # documenting placeholders so unedited strings are obvious during play.
    strings = db.Column(db.JSON, nullable=True, default=default_card_strings)
    # The card's Lua effect script (the body of c<cdb_id>.lua). Plain text:
    # newlines and indentation are preserved verbatim. NULL = no script yet.
    script = db.Column(db.Text, nullable=True)

    # --- Text boxes -------------------------------------------------------
    # Box A — the "spell/trap/pendulum" text box. Used by Spell & Trap cards,
    # AND by the Pendulum half of a Pendulum monster.
    effect_conditions = db.Column(db.Text, nullable=True)  # limits/procedures
    effect_text = db.Column(db.Text, nullable=True)        # the actual effects
    # Box B — the Monster text box (monsters only).
    materials = db.Column(db.Text, nullable=True)          # Fusion/Synchro/Xyz/Link
    monster_conditions = db.Column(db.Text, nullable=True)
    monster_effect = db.Column(db.Text, nullable=True)

    # ----------------------------------------------------------------- repr
    def __repr__(self):
        return f"<Card id={self.id} name={self.name!r} {self.category.value}>"

    # -------------------------------------------------- category convenience
    @property
    def is_monster(self):
        return self.category == CardCategory.MONSTER

    @property
    def is_spell(self):
        return self.category == CardCategory.SPELL

    @property
    def is_trap(self):
        return self.category == CardCategory.TRAP

    @property
    def is_link(self):
        return self.summon_type == MonsterSummonType.LINK

    @property
    def is_extra_deck(self):
        return self.summon_type in {
            MonsterSummonType.FUSION, MonsterSummonType.SYNCHRO,
            MonsterSummonType.XYZ, MonsterSummonType.LINK,
        }

    @property
    def shows_def(self):
        """Link monsters have no DEF."""
        return self.is_monster and not self.is_link

    @property
    def has_materials(self):
        return self.is_extra_deck

    # ----------------------------------------------------- .cdb export helpers
    @property
    def export_setcodes(self):
        """Stored set codes as a clean list of ints (drops blanks/zeros)."""
        return [int(c) for c in (self.setcodes or []) if c]

    @property
    def export_strings(self):
        """Card strings to write to the cdb, falling back to the defaults when
        a card predates this feature (NULL column)."""
        return list(self.strings) if self.strings else default_card_strings()

    # ----------------------------------------------------- render helpers
    @property
    def level_label(self):
        """What the `level` number means for this monster."""
        if self.is_link:
            return "Link"
        if self.summon_type == MonsterSummonType.XYZ:
            return "Rank"
        return "Level"

    @property
    def link_rating(self):
        """For Link monsters the rating IS the arrow count — single source."""
        return len(self.link_arrows or []) if self.is_link else None

    @property
    def display_attribute(self):
        """Attribute icon to show: monsters use their stored attribute;
        Spell/Trap cards use the SPELL / TRAP icon."""
        if self.is_spell:
            return "SPELL"
        if self.is_trap:
            return "TRAP"
        return self.attribute.value if self.attribute else None

    @property
    def frame(self):
        """The base visual frame key for the renderer (pendulum is layered on
        separately via `is_pendulum`)."""
        if self.is_spell:
            return "spell"
        if self.is_trap:
            return "trap"
        if self.summon_type:                 # ritual/fusion/synchro/xyz/link
            return self.summon_type.name.lower()
        return "effect" if self.is_effect else "normal"

    @property
    def type_line(self):
        """Human type line. Monsters read '[ Illusion / Effect ]'; Spell/Trap
        cards read their subtype as an adjective — '[ Field Spell ]',
        '[ Counter Trap ]' — never the slash form used for monsters."""
        if self.is_spell:
            return f"[ {self.spell_trap_type.value} Spell ]" if self.spell_trap_type else "[ Spell ]"
        if self.is_trap:
            return f"[ {self.spell_trap_type.value} Trap ]" if self.spell_trap_type else "[ Trap ]"
        parts = []
        if self.race:
            parts.append(self.race.value)
        if self.summon_type:
            parts.append(self.summon_type.value)
        if self.ability:
            parts.append(self.ability.value)
        if self.is_pendulum:
            parts.append("Pendulum")
        if self.is_tuner:
            parts.append("Tuner")
        parts.append("Effect" if self.is_effect else "Normal")
        return "[ " + " / ".join(parts) + " ]"

    def _copy_typeline(self):
        """Compact bracketed type line for the plaintext export, e.g.
        ``[Rock/Fusion/Pendulum/Effect]``, ``[Ritual Spell]``, ``[Counter Trap]``."""
        if self.is_spell:
            sub = self.spell_trap_type.value if self.spell_trap_type else None
            return f"[{sub} Spell]" if sub else "[Spell]"
        if self.is_trap:
            sub = self.spell_trap_type.value if self.spell_trap_type else None
            return f"[{sub} Trap]" if sub else "[Trap]"
        parts = []
        if self.race:
            parts.append(self.race.value)
        if self.summon_type:
            parts.append(self.summon_type.value)
        if self.ability:
            parts.append(self.ability.value)
        if self.is_pendulum:
            parts.append("Pendulum")
        if self.is_tuner:
            parts.append("Tuner")
        parts.append("Effect" if self.is_effect else "Normal")
        return "[" + "/".join(parts) + "]"

    @property
    def copy_text(self):
        """The card rendered as nicely-formatted plaintext, for the "copy card
        as text" button on the immersive list/reading view. Mirrors exactly what
        that view shows (header → rank/scale/arrows → pendulum effect → type line
        → materials/conditions/effects → stats)."""
        lines = []

        # Header: Name [ATTRIBUTE] [ID: passcode]
        head = self.name or "Unnamed card"
        if self.display_attribute:
            head += f" [{self.display_attribute}]"
        if self.cdb_id is not None:
            head += f" [ID: {self.cdb_id}]"
        lines.append(head)

        # Rank/Level stars, link arrows, pendulum scale.
        if self.is_monster:
            if self.is_link:
                arrows = "".join(LINK_ARROW_EMOJI[c] for c in LINK_ARROW_PLAINTEXT_ORDER
                                 if c in (self.link_arrows or []))
                if arrows:
                    lines.append(arrows)
            elif self.level:
                lines.append("✪" * self.level)
            if self.is_pendulum and self.pendulum_scale is not None:
                lines.append(f"◄{self.pendulum_scale}►")

        # Pendulum effect box (sits above the monster type line).
        if self.is_pendulum and (self.effect_conditions or self.effect_text):
            lines.append("[Pendulum Effect]")
            if self.effect_conditions:
                lines.append(self.effect_conditions)
            lines.extend(_effect_lines(self.effect_text))

        # Type line.
        lines.append(self._copy_typeline())

        # Body: materials, then conditions/procedures, then numbered effects.
        if self.has_materials and self.materials:
            lines.append(self.materials)
        conditions = self.monster_conditions if self.is_monster else self.effect_conditions
        if conditions:
            lines.append(conditions)
        effect = self.monster_effect if self.is_monster else self.effect_text
        lines.extend(_effect_lines(effect))

        # Stats.
        if self.is_monster:
            atk = self.atk if self.atk is not None else "?"
            if self.is_link:
                lines.append(f"ATK/{atk}\tLINK-{self.link_rating or 0}")
            else:
                def_ = self.def_ if self.def_ is not None else "?"
                lines.append(f"{atk}/{def_}")

        return "\n".join(lines)

    @property
    def svg_state(self):
        """Normalised dict matching the JS builder's readState() shape, so the
        same SVG renderer can draw this card anywhere a finished render image
        is missing."""
        st = self.summon_type
        return {
            "name": self.name or "",
            "isMonster": self.is_monster,
            "isSpell": self.is_spell,
            "isTrap": self.is_trap,
            "summonType": st.name if st else "",
            "summonLabel": st.value if st else "",
            "isLink": self.is_link,
            "isXyz": st == MonsterSummonType.XYZ,
            "isExtra": self.is_extra_deck,
            "isEffect": bool(self.is_effect),
            "isPendulum": bool(self.is_pendulum),
            "isTuner": bool(self.is_tuner),
            "attribute": self.attribute.name if self.attribute else "",
            "race": self.race.value if self.race else "",
            "ability": self.ability.value if self.ability else "",
            "level": self.level or 0,
            "pendScale": self.pendulum_scale,
            "atk": str(self.atk) if self.atk is not None else "",
            "def": str(self.def_) if self.def_ is not None else "",
            "arrows": self.link_arrows or [],
            "artImage": self.art_image or "",
            "effectConditions": self.effect_conditions or "",
            "effectText": self.effect_text or "",
            "materials": self.materials or "",
            "monsterConditions": self.monster_conditions or "",
            "monsterEffect": self.monster_effect or "",
        }

    # ------------------------------------------------------- light validation
    @validates("level")
    def _check_level(self, key, value):
        if value is not None and not (0 <= value <= 13):
            raise ValueError("level/rank/link-rating must be 0–13")
        return value

    @validates("pendulum_scale")
    def _check_scale(self, key, value):
        if value is not None and not (0 <= value <= 13):
            raise ValueError("pendulum_scale must be 0–13")
        return value

    @validates("spell_trap_type")
    def _check_subtype(self, key, value):
        # Only meaningful once category is set; skip if not yet assigned.
        if value is None or self.category is None:
            return value
        if self.category == CardCategory.SPELL and value not in _SPELL_SUBTYPES:
            raise ValueError(f"{value.value} is not a valid Spell subtype")
        if self.category == CardCategory.TRAP and value not in _TRAP_SUBTYPES:
            raise ValueError(f"{value.value} is not a valid Trap subtype")
        return value


# ===========================================================================
#  ARTICLE  +  ARTICLE↔CARD link
# ===========================================================================
class ArticleCard(db.Model):
    """A featured Card placed inside an Article (optionally within a section),
    with ordering and an optional caption (lore / tip / comment)."""
    __tablename__ = "article_card"

    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False)
    card_id = db.Column(db.Integer, db.ForeignKey("card.id"), nullable=False)
    section_id = db.Column(
        db.Integer, db.ForeignKey("article_section.id"), nullable=True
    )
    position = db.Column(db.Integer, nullable=False, default=0)
    # Free-text note shown under the card (lore / tip / comment). No length cap.
    caption = db.Column(db.Text, nullable=True)

    card = db.relationship("Card")

    def __repr__(self):
        return f"<ArticleCard id={self.id} article={self.article_id} card={self.card_id}>"


class ArticleSection(db.Model):
    """An ordered section within an Article: a heading, optional prose, and the
    cards shown beneath it."""
    __tablename__ = "article_section"

    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)
    heading = db.Column(db.String(200), nullable=True)
    body = db.Column(db.Text, nullable=True)

    cards = db.relationship(
        "ArticleCard",
        backref="section",
        order_by="ArticleCard.position",
        lazy="selectin",
    )

    def __repr__(self):
        return f"<ArticleSection id={self.id} heading={self.heading!r}>"


class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(160), nullable=False)
    subtitle = db.Column(db.String(200), nullable=True)
    slug = db.Column(db.String(180), unique=True, nullable=True)  # nice URLs
    description = db.Column(db.String(280), nullable=False)  # short grid blurb
    overview = db.Column(db.Text, nullable=True)  # full intro text
    body = db.Column(db.Text, nullable=True)  # legacy / unused
    cover_image = db.Column(db.String(255), nullable=True)   # optional

    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    status = db.Column(
        db.Enum(ArticleStatus), nullable=False, default=ArticleStatus.DRAFT
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    published_at = db.Column(db.DateTime, nullable=True)

    # Featured cards, ordered. `card_links` are the association rows;
    # `cards` is a convenience proxy straight to the Card objects.
    card_links = db.relationship(
        "ArticleCard",
        backref="article",
        order_by="ArticleCard.position",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    cards = association_proxy("card_links", "card")

    sections = db.relationship(
        "ArticleSection",
        backref="article",
        order_by="ArticleSection.position",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    comments = db.relationship(
        "Comment",
        backref="article",
        cascade="all, delete-orphan",
        order_by="Comment.created_at.desc()",
        lazy="selectin",
    )

    @property
    def comment_count(self):
        return len(self.comments)

    @property
    def card_count(self):
        """Cards featured, clamped to 1–3 for the stage widget."""
        return max(1, min(3, len(self.card_links)))

    def __repr__(self):
        return f"<Article id={self.id} title={self.title!r}>"


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(
        db.Integer, db.ForeignKey("article.id"), nullable=False
    )
    author_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    author_name = db.Column(db.String(80), nullable=False, default="Anonymous")
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Comment id={self.id} author={self.author_name!r}>"