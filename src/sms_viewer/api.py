"""
API blueprint for SMS Viewer.

Provides RESTful JSON endpoints for import, export, thread pagination, message loading, and FTS search.
"""

from pathlib import Path
from flask import Blueprint, current_app, jsonify, request

from sms_viewer.importer import get_import_history, import_backup_file

api_bp = Blueprint("api", __name__)


def _get_db_path() -> Path:
    """Helper to get DB path from current app config."""
    path = current_app.config.get("DATABASE_PATH") or current_app.config.get("DB_PATH")
    return Path(path)


@api_bp.route("/search")
def search():
    """Full-text search API (Phase 4)."""
    return jsonify({"results": [], "total": 0, "page": 1})


@api_bp.route("/threads")
def threads():
    """Thread list API for infinite scroll (Phase 3)."""
    return jsonify({"threads": [], "total": 0, "page": 1})


@api_bp.route("/messages/<path:address>")
def messages(address: str):
    """Paginated messages for a thread (Phase 3)."""
    return jsonify({"messages": [], "address": address, "total": 0, "page": 1})


@api_bp.route("/import", methods=["POST"])
def import_sms():
    """ZIP/NDJSON import endpoint."""
    uploaded_file = request.files.get("file") or request.files.get("backup")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"error": "No file uploaded. Please select a .zip or .ndjson backup file."}), 400

    filename = uploaded_file.filename
    db_path = _get_db_path()

    try:
        result = import_backup_file(uploaded_file.stream, filename, db_path)
        return jsonify(result), 200
    except Exception as err:
        return jsonify({"error": f"Import failed: {str(err)}"}), 500


@api_bp.route("/import/history", methods=["GET"])
def import_history():
    """Retrieve import history log records."""
    db_path = _get_db_path()
    try:
        history = get_import_history(db_path)
        return jsonify({"history": history}), 200
    except Exception as err:
        return jsonify({"error": f"Failed to fetch import history: {str(err)}"}), 500


@api_bp.route("/export")
def export_sms():
    """Date-range JSON export (Phase 5)."""
    return jsonify({"error": "Export not yet implemented"}), 501
