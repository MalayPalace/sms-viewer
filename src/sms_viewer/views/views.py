"""
Main views blueprint for SMS Viewer.

Provides page routes for thread list, conversation detail, search, import, and export views using DatabaseHelper.
"""

from pathlib import Path
from flask import Blueprint, current_app, render_template, request

from sms_viewer.database.db_helper import DatabaseHelper
from sms_viewer.feature.search import search_messages, search_messages_count
from sms_viewer.rest.auth import login_required
from sms_viewer.utils import group_messages_by_date

views_bp = Blueprint("views", __name__)


def _get_db_helper() -> DatabaseHelper:
    """Obtain DatabaseHelper for current application configuration."""
    path = current_app.config.get("DATABASE_PATH") or current_app.config.get("DB_PATH")
    return DatabaseHelper(Path(path))


@views_bp.route("/")
@login_required
def threads():
    """Thread list view — the main inbox screen."""
    db_helper = _get_db_helper()
    initial_limit = 50
    rows = db_helper.get_threads(limit=initial_limit, offset=0)
    total_count = db_helper.get_threads_count()
    has_more = len(rows) < total_count

    return render_template(
        "threads.html",
        threads=rows,
        total_count=total_count,
        has_more=has_more,
    )


@views_bp.route("/thread/<path:address>")
@login_required
def conversation(address: str):
    """Conversation view for a single sender/address."""
    db_helper = _get_db_helper()
    # Mark messages as read when viewing conversation
    db_helper.mark_thread_read(address)

    messages = db_helper.get_messages_by_address(address)
    date_groups = group_messages_by_date(messages)

    return render_template(
        "conversation.html",
        address=address,
        messages=messages,
        date_groups=date_groups,
        total_count=len(messages),
    )


@views_bp.route("/search")
@login_required
def search():
    """Full-text search results page."""
    db_helper = _get_db_helper()
    raw_q = request.args.get("q", "").strip()

    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    limit = 20
    offset = (page - 1) * limit

    results = []
    total = 0
    has_more = False

    if raw_q:
        results = search_messages(db_helper, query=raw_q, limit=limit, offset=offset)
        total = search_messages_count(db_helper, query=raw_q)
        has_more = (offset + len(results)) < total

    return render_template(
        "search_results.html",
        query=raw_q,
        results=results,
        total=total,
        page=page,
        has_more=has_more,
        prev_page=page - 1 if page > 1 else None,
        next_page=page + 1 if has_more else None,
    )


@views_bp.route("/import")
@login_required
def import_page():
    """Import page."""
    db_helper = _get_db_helper()
    import_log = db_helper.get_import_history()
    return render_template("import.html", import_log=import_log)


@views_bp.route("/export")
@login_required
def export_page():
    """Export page (Phase 5)."""
    return render_template("export.html")
