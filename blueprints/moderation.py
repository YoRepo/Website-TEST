# path: blueprints/moderation.py
"""Content moderation: reader reports + a staff review queue + takedowns.

Flow: anyone can *report* a card or article (rate-limited). Staff (moderators
and admins) see the open reports in a queue, can view the flagged content, and
either *hide* it (a reversible takedown that removes it from every public
surface) or *dismiss* the report. Hiding is soft — nothing is deleted — so an
accidental takedown is one click to undo.
"""

from datetime import datetime
from urllib.parse import urlsplit

from flask import (
    Blueprint, current_app, flash, redirect, render_template, request, url_for,
)
from flask_login import current_user

from extensions import db, limiter
from blueprints.auth import staff_required
from models import Article, Card, Report, ReportStatus, REPORT_REASON_MAX
from security import normalize_redirect_target

moderation_bp = Blueprint("moderation", __name__)

# The content types that can be reported/hidden. Keep in sync with
# Report.content_type. Each maps to its model and a human label.
REPORTABLE = {
    "card": (Card, "card"),
    "article": (Article, "article"),
}


def _resolve(content_type, content_id):
    entry = REPORTABLE.get(content_type)
    if entry is None:
        return None
    return db.session.get(entry[0], content_id)


def hold_for_review_if_required(obj):
    """Pre-moderation gate. When REQUIRE_UPLOAD_REVIEW is on, hide freshly
    created content by a non-staff user so a moderator must approve it before it
    goes public. Reuses the takedown plumbing: the object is hidden with
    ``hidden_by_id`` left NULL, which marks it *pending* (as opposed to a staff
    takedown, which records who hid it). Call before commit. Returns True when
    the object was held. Off by default — instant publishing is unchanged."""
    if not current_app.config.get("REQUIRE_UPLOAD_REVIEW"):
        return False
    if current_user.is_authenticated and current_user.is_staff:
        return False   # trusted authors publish immediately
    obj.is_hidden = True
    obj.hidden_at = datetime.utcnow()
    obj.hidden_by_id = None
    return True


def _pending_count():
    """How many items are awaiting first approval (hidden, no takedown author)."""
    n = 0
    for model, _label in REPORTABLE.values():
        n += model.query.filter(model.is_hidden.is_(True),
                                model.hidden_by_id.is_(None)).count()
    return n


def _safe_redirect(target):
    """Same-site relative path only (open-redirect guard). Folds backslashes
    first so ``/\\evil.com`` can't masquerade as a relative path."""
    target = normalize_redirect_target(target)
    if not target:
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return None
    if not parts.path.startswith("/") or parts.path.startswith("//"):
        return None
    return target


# ---------------------------------------------------------------------- report
@moderation_bp.route("/report", methods=["POST"])
@limiter.limit("3 per minute; 15 per hour")
def report():
    """Accept a reader's report of a card or article. Open to anonymous
    visitors too (rate-limited above) so anyone who sees something wrong can
    flag it."""
    content_type = (request.form.get("content_type") or "").strip()
    try:
        content_id = int(request.form.get("content_id") or 0)
    except ValueError:
        content_id = 0
    reason = (request.form.get("reason") or "").strip()[:REPORT_REASON_MAX] or None
    back = _safe_redirect(request.form.get("next")) or url_for("main.index")

    obj = _resolve(content_type, content_id)
    if obj is None:
        flash("That content could not be found.", "error")
        return redirect(back)

    db.session.add(Report(
        content_type=content_type, content_id=content_id, reason=reason,
        reporter_id=current_user.id if current_user.is_authenticated else None,
    ))
    db.session.commit()
    flash("Thanks for flagging this — a moderator will take a look.", "success")
    return redirect(back)


# ----------------------------------------------------------------------- queue
_STATUS_TABS = {
    "open": ReportStatus.OPEN,
    "resolved": ReportStatus.RESOLVED,
    "dismissed": ReportStatus.DISMISSED,
}


@moderation_bp.route("/")
@staff_required
def queue():
    tab = (request.args.get("status") or "open").lower()
    status = _STATUS_TABS.get(tab, ReportStatus.OPEN)
    if tab not in _STATUS_TABS:
        tab = "open"

    reports = (Report.query.filter(Report.status == status)
               .order_by(Report.created_at.desc()).all())
    # Pair each report with its live content object (None if since deleted).
    items = [{"report": r, "obj": _resolve(r.content_type, r.content_id)}
             for r in reports]
    open_count = Report.query.filter(Report.status == ReportStatus.OPEN).count()
    return render_template("moderation/queue.html", items=items, tab=tab,
                           open_count=open_count, pending_count=_pending_count())


@moderation_bp.route("/pending")
@staff_required
def pending():
    """Content awaiting first approval (only populated when REQUIRE_UPLOAD_REVIEW
    is enabled). Approving is just an unhide; rejecting is a normal takedown."""
    items = []
    for content_type, (model, _label) in REPORTABLE.items():
        rows = (model.query.filter(model.is_hidden.is_(True),
                                   model.hidden_by_id.is_(None))
                .order_by(model.hidden_at.desc()).all())
        items.extend({"content_type": content_type, "obj": obj} for obj in rows)
    items.sort(key=lambda it: it["obj"].hidden_at or datetime.min, reverse=True)
    return render_template("moderation/pending.html", items=items,
                           enabled=bool(current_app.config.get("REQUIRE_UPLOAD_REVIEW")),
                           open_count=Report.query.filter(
                               Report.status == ReportStatus.OPEN).count())


# ------------------------------------------------------------------- takedowns
def _resolve_open_reports(content_type, content_id):
    """Mark every OPEN report for this content as RESOLVED (called on hide)."""
    Report.query.filter(
        Report.content_type == content_type,
        Report.content_id == content_id,
        Report.status == ReportStatus.OPEN,
    ).update({"status": ReportStatus.RESOLVED,
              "handled_by_id": current_user.id,
              "handled_at": datetime.utcnow()},
             synchronize_session=False)


@moderation_bp.route("/<content_type>/<int:content_id>/hide", methods=["POST"])
@staff_required
def hide(content_type, content_id):
    obj = _resolve(content_type, content_id)
    if obj is None:
        flash("That content could not be found.", "error")
        return redirect(url_for("moderation.queue"))
    obj.is_hidden = True
    obj.hidden_at = datetime.utcnow()
    obj.hidden_by_id = current_user.id
    _resolve_open_reports(content_type, content_id)
    db.session.commit()
    flash("Taken down — it's no longer publicly visible.", "success")
    return redirect(_safe_redirect(request.form.get("next"))
                    or url_for("moderation.queue"))


@moderation_bp.route("/<content_type>/<int:content_id>/unhide", methods=["POST"])
@staff_required
def unhide(content_type, content_id):
    obj = _resolve(content_type, content_id)
    if obj is None:
        flash("That content could not be found.", "error")
        return redirect(url_for("moderation.queue"))
    obj.is_hidden = False
    obj.hidden_at = None
    obj.hidden_by_id = None
    db.session.commit()
    flash("Restored — it's publicly visible again.", "success")
    return redirect(_safe_redirect(request.form.get("next"))
                    or url_for("moderation.queue"))


@moderation_bp.route("/report/<int:report_id>/dismiss", methods=["POST"])
@staff_required
def dismiss(report_id):
    r = Report.query.get_or_404(report_id)
    r.status = ReportStatus.DISMISSED
    r.handled_by_id = current_user.id
    r.handled_at = datetime.utcnow()
    db.session.commit()
    flash("Report dismissed.", "success")
    return redirect(_safe_redirect(request.form.get("next"))
                    or url_for("moderation.queue"))
