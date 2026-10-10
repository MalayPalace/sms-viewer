"""
Main views blueprint for SMS Viewer.

Phase 3 will implement the full thread list and conversation views.
This stub provides skeleton routes so the app can start and be tested in Phase 1.
"""

from flask import Blueprint, current_app, redirect, render_template, url_for

from sms_viewer.auth import login_required
from sms_viewer.db import get_db
from sms_viewer.importer import get_import_history

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
@login_required
def threads():
    """Thread list view — the main inbox screen."""
    db_path = current_app.config["DATABASE_PATH"]
    db = get_db(db_path)

    # Aggregate: one row per address, latest message date, total count
    rows = db.execute("""
        SELECT
            address,
            MAX(date)  AS latest_date,
            COUNT(*)   AS message_count,
            (
                SELECT body FROM messages m2
                WHERE m2.address = messages.address
                ORDER BY m2.date DESC LIMIT 1
            ) AS last_body
        FROM messages
        GROUP BY address
        ORDER BY latest_date DESC
    """).fetchall()

    return render_template("threads.html", threads=rows)


@views_bp.route("/thread/<path:address>")
@login_required
def conversation(address: str):
    """Conversation view for a single sender/address."""
    db_path = current_app.config["DATABASE_PATH"]
    db = get_db(db_path)

    messages = db.execute(
        "SELECT * FROM messages WHERE address = ? ORDER BY date ASC",
        (address,),
    ).fetchall()

    return render_template("conversation.html", address=address, messages=messages)


@views_bp.route("/search")
@login_required
def search():
    """Search results page (Phase 4)."""
    query = ""
    return render_template("search_results.html", query=query, results=[])


@views_bp.route("/import")
@login_required
def import_page():
    """Import page (Phase 2)."""
    db_path = current_app.config["DATABASE_PATH"]
    import_log = get_import_history(db_path)
    return render_template("import.html", import_log=import_log)


@views_bp.route("/export")
@login_required
def export_page():
    """Export page (Phase 5)."""
    return render_template("export.html")
