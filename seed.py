from datetime import datetime, timedelta
from extensions import db
from models import (
    User, CardSet, Card, Article, ArticleCard, Comment,
    CardCategory, Attribute, Race, MonsterSummonType, SpellTrapType,
    ArticleStatus, UserRole,
)

def seed_if_empty():
    # Don't seed anything
    return
    if User.query.first() is not None:
        return

    now = datetime.utcnow()

    pyro = User(username="PyroDuelist", display_name="Pyro", role=UserRole.ADMIN)
    abyss = User(username="AbyssalArchitect", display_name="The Architect")
    novice = User(username="NoviceCrafter", display_name="Novice")
    # DEV-ONLY seed credentials. Change/remove before any real deployment.
    for u in (pyro, abyss, novice):
        u.set_password("dev-password-change-me")
    db.session.add_all([pyro, abyss, novice])

    embers = CardSet(name="Embers of Creation", code="EMBR", owner=pyro,
                     description="A burn-aggro toolbox.")
    tides = CardSet(name="Tideborn Depths", code="TIDE", owner=abyss,
                    description="Water control and lockdown.")
    first = CardSet(name="First Drafts", code="FRST", owner=novice,
                    description="Where everyone starts.")
    db.session.add_all([embers, tides, first])

    cards = {}
    cards["wyrm"] = Card(
        name="Emberbrand Wyrm", category=CardCategory.MONSTER, owner=pyro,
        card_set=embers, is_effect=True, attribute=Attribute.FIRE,
        race=Race.DRAGON, level=7, atk=2500, def_=2000,
        monster_conditions="You can only use this effect once per turn.",
        monster_effect="During each Standby Phase: inflict 300 damage to your opponent.")
    cards["inferno"] = Card(
        name="Inferno Sprite", category=CardCategory.MONSTER, owner=pyro,
        card_set=embers, is_effect=True, is_tuner=True, attribute=Attribute.FIRE,
        race=Race.PYRO, level=2, atk=800, def_=200,
        monster_effect="If this card is sent to the GY: add 1 FIRE monster from your Deck to your hand.")
    cards["surge"] = Card(
        name="Tidal Surge", category=CardCategory.SPELL, owner=abyss,
        card_set=tides, spell_trap_type=SpellTrapType.FIELD,
        effect_text="All WATER monsters on the field gain 300 ATK.")
    cards["riptide"] = Card(
        name="Mirror Riptide", category=CardCategory.TRAP, owner=abyss,
        card_set=tides, spell_trap_type=SpellTrapType.COUNTER,
        effect_conditions="When an opponent activates a Spell/Trap Card:",
        effect_text="Negate the activation and destroy that card.")
    cards["conduit"] = Card(
        name="Tideborn Conduit", category=CardCategory.MONSTER, owner=abyss,
        card_set=tides, is_effect=True, summon_type=MonsterSummonType.LINK,
        attribute=Attribute.WATER, race=Race.CYBERSE, level=2, atk=1600,
        link_arrows=["L", "R"], materials="2 WATER monsters",
        monster_effect="Monsters this card points to cannot be destroyed by card effects.")
    cards["abyss"] = Card(
        name="Abyssal Warden", category=CardCategory.MONSTER, owner=abyss,
        card_set=tides, is_effect=True, attribute=Attribute.WATER,
        race=Race.SEA_SERPENT, level=4, atk=1700, def_=1200,
        monster_effect="Your opponent must pay 500 LP to Special Summon a monster.")
    cards["prism"] = Card(
        name="Prism Archivist", category=CardCategory.MONSTER, owner=novice,
        card_set=first, is_effect=True, is_pendulum=True, attribute=Attribute.LIGHT,
        race=Race.SPELLCASTER, level=4, pendulum_scale=5, atk=1500, def_=1000,
        effect_conditions="Once per turn:",
        effect_text="You can add 1 Spell from your Deck to your hand.",
        monster_effect="If this card is destroyed: draw 1 card.")
    cards["quartz"] = Card(
        name="Quartz Familiar", category=CardCategory.MONSTER, owner=novice,
        card_set=first, attribute=Attribute.EARTH, race=Race.ROCK,
        level=3, atk=1000, def_=1800)  # vanilla Normal monster

    db.session.add_all(list(cards.values()))
    db.session.commit()  # cards need ids before we link them

    article_specs = [
        ("Emberbrand Wyrm, reforged", pyro,
         "A burn-aggro finisher that punishes stalling — every Standby Phase it gets hungrier.",
         [("wyrm", "The finisher"), ("inferno", "The enabler")], 7),
        ("The Tideborn control package", abyss,
         "A two-card lock that floods the board and taxes every Special Summon.",
         [("conduit", None), ("abyss", None), ("surge", None)], 12),
        ("Mirror Riptide is underrated", abyss,
         "One counter trap that quietly wins games. Here's why I run three.",
         [("riptide", None)], 4),
        ("Prism Archivist: my first custom", novice,
         "Gentle, fair, and a little janky — the card that got me into designing.",
         [("prism", None)], 2),
        ("A love letter to vanilla monsters", novice,
         "Sometimes a clean 1000/1800 with no text is all a set needs.",
         [("quartz", None)], 1),
    ]
    authors = ["DeckBuilder42", "MillenniumFan", "TopTierTed", "CasualKaiba",
               "RulingsRebecca", "SetRotation", "BlueEyesBeliever", "OTK_Olly"]
    bodies = [
        "This is clean — love the design space.",
        "The balance feels tight. Have you playtested it?",
        "Art's gorgeous. What program did you use?",
        "I'd run three of these immediately.",
        "Slightly too strong for my casual table, but stunning.",
        "The effect wording could be tighter, but the idea slaps.",
        "Finally, a custom that isn't just a bigger beatstick.",
        "Sleeving these up for my next locals.",
    ]
    for i, (title, author, desc, links, n) in enumerate(article_specs):
        created = now - timedelta(days=i, hours=i * 2)
        art = Article(title=title, author=author, description=desc,
                      body=f"Full write-up for “{title}” lands in a later step.",
                      status=ArticleStatus.PUBLISHED,
                      created_at=created, published_at=created)
        for pos, (key, caption) in enumerate(links):
            art.card_links.append(ArticleCard(card=cards[key], position=pos, caption=caption))
        for c in range(n):
            art.comments.append(Comment(author_name=authors[c % len(authors)],
                                        body=bodies[c % len(bodies)],
                                        created_at=created + timedelta(hours=c + 1)))
        db.session.add(art)
    db.session.commit()