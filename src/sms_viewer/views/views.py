"""
Main views blueprint for SMS Viewer.

Provides page routes for thread list, conversation detail, search, import, and export views using DatabaseHelper.
"""

from pathlib import Path
from flask import Blueprint, current_app, render_template

from sms_viewer.database.db_helper import DatabaseHelper
from sms_viewer.rest.auth import login_required

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
    rows = db_helper.get_threads()
    return render_template("threads.html", threads=rows)


@views_bp.route("/thread/<path:address>")
@login_required
def conversation(address: str):
    """Conversation view for a single sender/address."""
    db_helper = _get_db_helper()
    messages = db_helper.get_messages_by_address(address)
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
    """Import page."""
    db_helper = _get_db_helper()
    import_log = db_helper.get_import_history()
    return render_template("import.html", import_log=import_log)


@views_bp.route("/export")
@login_required
def export_page():
    """Export page (Phase 5)."""
    return render_template("export.html")
