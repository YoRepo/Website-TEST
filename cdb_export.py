# path: cdb_export.py
"""Export website Cards to an EDOPro / YGOPro ``.cdb`` database.

A ``.cdb`` is a plain SQLite3 file using Project Ignis "Datacorn"'s schema
(two tables: ``datas`` and ``texts``). Our :class:`models.Card` stores cards in
a friendlier, fully-structured shape; this module is the bridge that encodes
that structure into the bitfields EDOPro expects (``type``, ``race``,
``attribute``, ``level`` with packed pendulum scales, ``def`` carrying Link
markers, …).

The mapping is intentionally isolated from Flask so it can be unit-tested and
reused (CLI export, etc.). The only public entry point is :func:`build_cdb`.
"""

import sqlite3

from models import (
    Attribute, Race, CardCategory, MonsterSummonType, MonsterAbility,
    SpellTrapType, CDB_MAX_SETCODES, CDB_MAX_STRINGS, default_card_strings,
)

# ---------------------------------------------------------------------------
#  Datacorn's exact schema (verbatim from its src/gui/main_window.cpp), so the
#  files we emit open in Datacorn and EDOPro without complaint.
# ---------------------------------------------------------------------------
SQL_CREATE_DATAS = """
CREATE TABLE "datas" (
    "id"        INTEGER,
    "ot"        INTEGER,
    "alias"     INTEGER,
    "setcode"   INTEGER,
    "type"      INTEGER,
    "atk"       INTEGER,
    "def"       INTEGER,
    "level"     INTEGER,
    "race"      INTEGER,
    "attribute" INTEGER,
    "category"  INTEGER,
    PRIMARY KEY("id")
)
"""

SQL_CREATE_TEXTS = """
CREATE TABLE "texts" (
    "id"    INTEGER,
    "name"  TEXT, "desc" TEXT,
    "str1"  TEXT, "str2" TEXT, "str3" TEXT, "str4" TEXT,
    "str5"  TEXT, "str6" TEXT, "str7" TEXT, "str8" TEXT,
    "str9"  TEXT, "str10" TEXT, "str11" TEXT, "str12" TEXT,
    "str13" TEXT, "str14" TEXT, "str15" TEXT, "str16" TEXT,
    PRIMARY KEY("id")
)
"""

# ---------------------------------------------------------------------------
#  EDOPro bitfield constants
# ---------------------------------------------------------------------------
# Card scope. 0x3 == legal in both OCG and TCG (the sane default for customs).
OT_OCG_TCG = 0x1 | 0x2

_TYPE = {
    "MONSTER": 0x1, "SPELL": 0x2, "TRAP": 0x4,
    "NORMAL": 0x10, "EFFECT": 0x20, "FUSION": 0x40, "RITUAL": 0x80,
    "SPIRIT": 0x200, "UNION": 0x400, "GEMINI": 0x800, "TUNER": 0x1000,
    "SYNCHRO": 0x2000, "QUICKPLAY": 0x10000, "CONTINUOUS": 0x20000,
    "EQUIP": 0x40000, "FIELD": 0x80000, "COUNTER": 0x100000, "FLIP": 0x200000,
    "TOON": 0x400000, "XYZ": 0x800000, "PENDULUM": 0x1000000, "LINK": 0x4000000,
}

_ATTR = {
    Attribute.EARTH: 0x01, Attribute.WATER: 0x02, Attribute.FIRE: 0x04,
    Attribute.WIND: 0x08, Attribute.LIGHT: 0x10, Attribute.DARK: 0x20,
    Attribute.DIVINE: 0x40,
}

_RACE = {
    Race.WARRIOR: 0x1, Race.SPELLCASTER: 0x2, Race.FAIRY: 0x4, Race.FIEND: 0x8,
    Race.ZOMBIE: 0x10, Race.MACHINE: 0x20, Race.AQUA: 0x40, Race.PYRO: 0x80,
    Race.ROCK: 0x100, Race.WINGED_BEAST: 0x200, Race.PLANT: 0x400,
    Race.INSECT: 0x800, Race.THUNDER: 0x1000, Race.DRAGON: 0x2000,
    Race.BEAST: 0x4000, Race.BEAST_WARRIOR: 0x8000, Race.DINOSAUR: 0x10000,
    Race.FISH: 0x20000, Race.SEA_SERPENT: 0x40000, Race.REPTILE: 0x80000,
    Race.PSYCHIC: 0x100000, Race.DIVINE: 0x200000, Race.WYRM: 0x800000,
    Race.CYBERSE: 0x1000000, Race.ILLUSION: 0x2000000,
}

# Extra-deck summon frames -> their type flag.
_SUMMON_TYPE = {
    MonsterSummonType.RITUAL: _TYPE["RITUAL"],
    MonsterSummonType.FUSION: _TYPE["FUSION"],
    MonsterSummonType.SYNCHRO: _TYPE["SYNCHRO"],
    MonsterSummonType.XYZ: _TYPE["XYZ"],
    MonsterSummonType.LINK: _TYPE["LINK"],
}

_ABILITY = {
    MonsterAbility.SPIRIT: _TYPE["SPIRIT"], MonsterAbility.UNION: _TYPE["UNION"],
    MonsterAbility.GEMINI: _TYPE["GEMINI"], MonsterAbility.FLIP: _TYPE["FLIP"],
    MonsterAbility.TOON: _TYPE["TOON"],
}

_SPELLTRAP_SUBTYPE = {
    SpellTrapType.CONTINUOUS: _TYPE["CONTINUOUS"],
    SpellTrapType.FIELD: _TYPE["FIELD"],
    SpellTrapType.QUICK_PLAY: _TYPE["QUICKPLAY"],
    SpellTrapType.EQUIP: _TYPE["EQUIP"],
    SpellTrapType.RITUAL: _TYPE["RITUAL"],
    SpellTrapType.COUNTER: _TYPE["COUNTER"],
    # NORMAL adds no extra flag.
}

# Our arrow codes (models.LINK_ARROW_CODES) -> EDOPro link-marker bits, stored
# in the ``def`` column for Link monsters.
_LINK_MARKER = {
    "BL": 0x001, "B": 0x002, "BR": 0x004, "L": 0x008,
    "R": 0x020, "TL": 0x040, "T": 0x080, "TR": 0x100,
}

_PEND_SEPARATOR = "-" * 20


# ---------------------------------------------------------------------------
#  Per-field encoders
# ---------------------------------------------------------------------------
def carries_monster_stats(card):
    """True for cards whose data row holds monster stats: real monsters, and
    Trap Monsters (Traps that Summon themselves as a monster — the stats live
    in the data row exactly as for a monster, while the type stays a Trap)."""
    return card.is_monster or (card.is_trap and bool(card.is_trap_monster))


def encode_type(card):
    """The ``type`` bitfield for one Card."""
    t = 0
    if card.category == CardCategory.MONSTER:
        t |= _TYPE["MONSTER"]
        if card.summon_type in _SUMMON_TYPE:
            t |= _SUMMON_TYPE[card.summon_type]
        if card.is_pendulum:
            t |= _TYPE["PENDULUM"]
        if card.is_tuner:
            t |= _TYPE["TUNER"]
        if card.ability in _ABILITY:
            t |= _ABILITY[card.ability]
        # Effect vs Normal. Anything with an effect-bearing ability/summon is an
        # effect monster; otherwise honour the explicit is_effect flag.
        t |= _TYPE["EFFECT"] if card.is_effect else _TYPE["NORMAL"]
    elif card.category == CardCategory.SPELL:
        t |= _TYPE["SPELL"]
        t |= _SPELLTRAP_SUBTYPE.get(card.spell_trap_type, 0)
    elif card.category == CardCategory.TRAP:
        t |= _TYPE["TRAP"]
        t |= _SPELLTRAP_SUBTYPE.get(card.spell_trap_type, 0)
        # A Trap Monster may also carry monster subtypes (Effect / Tuner /
        # ability such as Toon). The base type stays a Trap; these are extra
        # bits, mirroring how the monster path encodes them.
        if card.is_trap_monster:
            if card.is_effect:
                t |= _TYPE["EFFECT"]
            if card.is_tuner:
                t |= _TYPE["TUNER"]
            if card.ability in _ABILITY:
                t |= _ABILITY[card.ability]
    return t


def encode_level(card):
    """The ``level`` column. For pendulums the scales are packed into the high
    bytes; for Links it carries the link rating; otherwise it's Level/Rank."""
    if not carries_monster_stats(card):
        return 0
    if card.is_link:
        return card.link_rating or 0
    level = card.level or 0
    if card.is_pendulum:
        scale = card.pendulum_scale or 0
        # (left_scale << 24) | (right_scale << 16) | level. Our model keeps a
        # single scale, so both sides use it.
        return (scale << 24) | (scale << 16) | (level & 0xFFFF)
    return level


def encode_def(card):
    """The ``def`` column — Link monsters store their arrow markers here."""
    if not carries_monster_stats(card):
        return 0
    if card.is_link:
        bits = 0
        for code in (card.link_arrows or []):
            bits |= _LINK_MARKER.get(code, 0)
        return bits
    return card.def_ or 0


def encode_attribute(card):
    if carries_monster_stats(card) and card.attribute:
        return _ATTR.get(card.attribute, 0)
    return 0


def encode_race(card):
    if carries_monster_stats(card) and card.race:
        return _RACE.get(card.race, 0)
    return 0


def encode_setcode(card):
    """Pack up to four 16-bit archetype codes into the 64-bit ``setcode``
    column: ``code0 | code1<<16 | code2<<32 | code3<<48``."""
    value = 0
    for i, code in enumerate(card.export_setcodes[:CDB_MAX_SETCODES]):
        value |= (int(code) & 0xFFFF) << (i * 16)
    return value


def encode_strings(card):
    """The 16 ``str1..str16`` values. The card's strings fill them in order
    (string id ``i`` → ``str(i+1)``); the rest are empty."""
    strings = [s or "" for s in (card.export_strings or default_card_strings())]
    strings = strings[:CDB_MAX_STRINGS]
    strings += [""] * (CDB_MAX_STRINGS - len(strings))
    return strings


def build_desc(card):
    """Flatten our split text boxes into the single ``desc`` EDOPro expects."""
    def joined(*parts):
        return "\n".join(p.strip() for p in parts if p and p.strip())

    if card.category == CardCategory.MONSTER:
        monster = joined(card.materials, card.monster_conditions,
                         card.monster_effect)
        if card.is_pendulum:
            pend = joined(card.effect_conditions, card.effect_text)
            blocks = []
            if pend:
                blocks.append("[ Pendulum Effect ]\n" + pend)
            blocks.append(_PEND_SEPARATOR)
            if monster:
                blocks.append(monster)
            return "\n".join(blocks)
        return monster
    # Spell / Trap: a single text box.
    return joined(card.effect_conditions, card.effect_text)


# ---------------------------------------------------------------------------
#  Row + database builders
# ---------------------------------------------------------------------------
def card_to_rows(cdb_id, card):
    """Return ``(datas_row, texts_row)`` tuples for one card under ``cdb_id``."""
    datas = (
        int(cdb_id),                 # id
        OT_OCG_TCG,                  # ot
        0,                           # alias
        encode_setcode(card),        # setcode (up to 4 packed archetype codes)
        encode_type(card),           # type
        card.atk if card.atk is not None else 0,
        encode_def(card),            # def
        encode_level(card),          # level
        encode_race(card),           # race
        encode_attribute(card),      # attribute
        0,                           # category (functional flags; unused)
    )
    texts = ((int(cdb_id), card.name or "", build_desc(card))
             + tuple(encode_strings(card)))
    return datas, texts


def build_cdb(path, items):
    """Write a ``.cdb`` at ``path`` from ``items`` — an iterable of
    ``(cdb_id, Card)`` pairs. Raises on duplicate ids so the caller can report
    it cleanly."""
    seen = set()
    con = sqlite3.connect(path)
    try:
        cur = con.cursor()
        cur.execute(SQL_CREATE_DATAS)
        cur.execute(SQL_CREATE_TEXTS)
        for cdb_id, card in items:
            cid = int(cdb_id)
            if cid in seen:
                raise ValueError(f"Duplicate card id {cid} in this .cdb.")
            seen.add(cid)
            datas, texts = card_to_rows(cid, card)
            cur.execute(
                "INSERT INTO datas VALUES (?,?,?,?,?,?,?,?,?,?,?)", datas)
            cur.execute(
                "INSERT INTO texts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                texts)
        con.commit()
    finally:
        con.close()
    return path
