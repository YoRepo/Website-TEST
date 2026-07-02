# path: blueprints/articles.py
"""The 'articles' blueprint: read, create, edit, and delete articles.

An article is a Title + Subtitle + Overview, then an ordered list of Sections.
Each section has a heading, optional prose, and any number of featured Cards
(ordered, each with an optional caption). The editor serialises the whole
structure to a hidden JSON field; this handler rebuilds sections + card links
from scratch on every save.
"""

import json
from datetime import datetime

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user, login_required

from extensions import db, limiter
from blueprints.auth import owner_or_admin
from blueprints.moderation import hold_for_review_if_required
from models import Article, ArticleCard, ArticleSection, ArticleStatus, Card

articles_bp = Blueprint("articles", __name__)

# Throttle article create/edit submissions. GET is exempt.
_WRITE_LIMIT = "12 per minute; 120 per hour"


def _clean(raw):
    raw = (raw or "").strip()
    return raw or None


def _cards_for_picker():
    """Card data for the editor's visual picker: enough to render a small image
    tile (finished render if present, else the inline SVG fallback) and to
    search by name or set."""
    return [{"id": c.id, "name": c.name, "type_line": c.type_line,
             "set": c.card_set.name if c.card_set else "",
             "render_image": c.render_image or "",
             "svg_state": c.svg_state}
            for c in Card.query.filter(Card.is_hidden.is_(False))
                               .order_by(Card.name).all()]


def _structure_from_article(article):
    """Turn a stored article into the editor's JSON shape (for prefill)."""
    sections = []
    loose = sorted((ac for ac in article.card_links if ac.section_id is None),
                   key=lambda a: a.position)
    if loose:
        sections.append({
            "heading": "", "body": "",
            "cards": [{"card_id": ac.card_id, "caption": ac.caption or ""}
                      for ac in loose],
        })
    for sec in article.sections:
        sections.append({
            "heading": sec.heading or "", "body": sec.body or "",
            "cards": [{"card_id": ac.card_id, "caption": ac.caption or ""}
                      for ac in sorted(sec.cards, key=lambda a: a.position)],
        })
    return {"sections": sections}


def _apply_article(article, form):
    article.title = (form.get("title") or "").strip()
    if not article.title:
        raise ValueError("Title is required.")
    article.subtitle = _clean(form.get("subtitle"))

    overview = (form.get("overview") or "").strip()
    if not overview:
        raise ValueError("Overview is required.")
    article.overview = overview
    article.description = (overview[:277] + "…") if len(overview) > 280 else overview

    article.cover_image = _clean(form.get("cover_image"))
    try:
        article.status = ArticleStatus[form.get("status", "DRAFT")]
    except KeyError:
        article.status = ArticleStatus.DRAFT
    if article.status == ArticleStatus.PUBLISHED and article.published_at is None:
        article.published_at = datetime.utcnow()

    structure = json.loads(form.get("structure") or '{"sections": []}')

    # Rebuild from scratch. Clear cards first (children), then sections.
    article.card_links.clear()
    db.session.flush()
    article.sections.clear()
    db.session.flush()

    pos = 0
    for si, sdata in enumerate(structure.get("sections", [])):
        sec = ArticleSection(heading=_clean(sdata.get("heading")),
                             body=_clean(sdata.get("body")), position=si)
        article.sections.append(sec)
        db.session.flush()  # assign sec.id
        for cdata in sdata.get("cards", []):
            try:
                card = Card.query.get(int(cdata.get("card_id")))
            except (TypeError, ValueError):
                card = None
            if card is None:
                continue
            ac = ArticleCard(card=card, position=pos,
                             caption=_clean(cdata.get("caption")))
            ac.section = sec
            article.card_links.append(ac)
            pos += 1
    return article


_ARTICLE_VIEWS = ("reading", "grid")


@articles_bp.route("/<int:article_id>")
def detail(article_id):
    article = Article.query.get_or_404(article_id)
    is_owner = current_user.is_authenticated and article.author_id == current_user.id
    is_staff = current_user.is_authenticated and current_user.is_staff
    if article.status != ArticleStatus.PUBLISHED:
        if not (current_user.is_authenticated
                and (current_user.is_admin or is_owner)):
            abort(404)   # 404, not 403 — don't confirm the draft exists
    # A hidden (moderated) article 404s for the public; the author and staff can
    # still reach it (staff to review/restore, the author to see it's gone).
    if article.is_hidden and not (is_staff or is_owner):
        abort(404)
    # `aview` (reading|grid) chooses how the featured cards are laid out; it's
    # preserved on the toggle links so the choice survives a no-JS reload.
    aview = request.args.get("aview", "reading")
    if aview not in _ARTICLE_VIEWS:
        aview = "reading"
    # Staff see hidden embedded cards (to review) and the article's moderation
    # controls; everyone else never sees hidden cards.
    return render_template("articles/detail.html", article=article, aview=aview,
                           can_moderate=is_staff)


def _safe_structure(raw):
    try:
        return json.loads(raw or '{"sections": []}')
    except json.JSONDecodeError:
        return {"sections": []}


@articles_bp.route("/new", methods=["GET", "POST"])
@limiter.limit(_WRITE_LIMIT, methods=["POST"])
@login_required
def new():
    if request.method == "POST":
        article = Article()
        try:
            _apply_article(article, request.form)
            article.author_id = current_user.id
            held = hold_for_review_if_required(article)
            db.session.add(article)
            db.session.commit()
            if held:
                flash(f"Created “{article.title}” — it's awaiting moderator "
                      "review before it appears publicly.", "success")
            else:
                flash(f"Created “{article.title}”.", "success")
            return redirect(url_for("articles.detail", article_id=article.id))
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            db.session.rollback()
            flash(f"Couldn't save: {exc}", "error")
            return render_template(
                "articles/form.html", mode="new", form=request.form,
                cards=_cards_for_picker(),
                structure_obj=_safe_structure(request.form.get("structure")))
    return render_template(
        "articles/form.html", mode="new", form={},
        cards=_cards_for_picker(), structure_obj={"sections": []})


@articles_bp.route("/<int:article_id>/edit", methods=["GET", "POST"])
@limiter.limit(_WRITE_LIMIT, methods=["POST"])
@login_required
def edit(article_id):
    article = Article.query.get_or_404(article_id)
    owner_or_admin(article.author_id)
    if request.method == "POST":
        try:
            _apply_article(article, request.form)
            db.session.commit()
            flash(f"Saved “{article.title}”.", "success")
            return redirect(url_for("articles.detail", article_id=article.id))
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            db.session.rollback()
            flash(f"Couldn't save: {exc}", "error")
            return render_template(
                "articles/form.html", mode="edit", article=article,
                form=request.form, cards=_cards_for_picker(),
                structure_obj=_safe_structure(request.form.get("structure")))
    return render_template(
        "articles/form.html", mode="edit", article=article,
        cards=_cards_for_picker(),
        structure_obj=_structure_from_article(article),
        form={
            "title": article.title,
            "subtitle": article.subtitle or "",
            "overview": article.overview or article.description or "",
            "cover_image": article.cover_image or "",
            "status": article.status.name,
        })


@articles_bp.route("/<int:article_id>/delete", methods=["POST"])
@login_required
def delete(article_id):
    article = Article.query.get_or_404(article_id)
    owner_or_admin(article.author_id)
    title = article.title
    db.session.delete(article)
    db.session.commit()
    flash(f"Deleted “{title}”.", "success")
    return redirect(url_for("main.index"))