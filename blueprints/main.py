# path: blueprints/main.py
"""The 'main' blueprint: the homepage, the about page, and card search.

The homepage renders the full article grid. The toolbar search box submits to
the /search route below, which looks up *cards* by name or by the set they
belong to and shows them on a dedicated results page (grid or list view).
"""

from flask import Blueprint, render_template, request

from extensions import db
from models import Article, ArticleStatus, Card, CardSet

main_bp = Blueprint("main", __name__)

# The two ways search results can be presented. `grid` shows card images in a
# 4-wide gallery; `list` shows the detailed rows used inside articles.
_SEARCH_VIEWS = ("grid", "list")


def _published_articles():
    """Newest-first list of PUBLISHED articles only.
    (Drop the status filter if you want drafts visible during development.)"""
    return (
        Article.query.filter(Article.status == ArticleStatus.PUBLISHED)
        .order_by(Article.created_at.desc())
        .all()
    )


@main_bp.route("/")
def index():
    """Home page: the full article grid, newest first."""
    return render_template("index.html", articles=_published_articles())


@main_bp.route("/search")
def search():
    """Search cards by card name keywords or by the name/code of their set.

    `view` (grid|list) chooses how matches are presented; it's preserved across
    the toggle links so the choice survives a no-JS page reload.
    """
    query = request.args.get("q", "").strip()
    view = request.args.get("view", "grid")
    if view not in _SEARCH_VIEWS:
        view = "grid"

    cards = []
    if query:
        like = f"%{query}%"
        cards = (
            Card.query
            .outerjoin(CardSet, Card.set_id == CardSet.id)
            .filter(
                db.or_(
                    Card.name.ilike(like),
                    CardSet.name.ilike(like),
                    CardSet.code.ilike(like),
                )
            )
            .order_by(Card.created_at.desc())
            .all()
        )
    return render_template(
        "search.html", cards=cards, search_query=query, view=view
    )


@main_bp.route("/about")
def about():
    """A short about page."""
    return render_template("about.html")