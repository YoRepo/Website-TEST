# path: blueprints/main.py
"""The 'main' blueprint: the homepage, the about page, and search.

The homepage renders the full article grid. The toolbar search box filters
that grid instantly in the browser (see static/js/main.js); the /search route
below is the no-JavaScript fallback and also powers shareable result URLs.
"""

from flask import Blueprint, render_template, request

from extensions import db
from models import Article, ArticleStatus, User

main_bp = Blueprint("main", __name__)


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
    """No-JS fallback search over title, author, and description."""
    query = request.args.get("q", "").strip()
    if query:
        like = f"%{query}%"
        results = (
            Article.query.filter(Article.status == ArticleStatus.PUBLISHED)
            .outerjoin(User, Article.author_id == User.id)
            .filter(
                db.or_(
                    Article.title.ilike(like),
                    Article.description.ilike(like),
                    User.username.ilike(like),
                    User.display_name.ilike(like),
                )
            )
            .order_by(Article.created_at.desc())
            .all()
        )
    else:
        results = _published_articles()
    return render_template("index.html", articles=results, search_query=query)


@main_bp.route("/about")
def about():
    """A short about page."""
    return render_template("about.html")