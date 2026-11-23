"""
API blueprint for SMS Viewer.

Provides RESTful JSON endpoints for import, export, thread pagination, message loading, and FTS search.
"""

from pathlib import Path
from flask import Blueprint, Response, current_app, jsonify, request, session

from sms_viewer.database.db_helper import DatabaseHelper
from sms_viewer.feature.exporter import count_messages, export_to_json, parse_date_range
from sms_viewer.feature.importer import get_import_history, import_backup_file
from sms_viewer.feature.search import parse_search_query, search_messages, search_messages_count
from sms_viewer.utils import avatar_color_index, avatar_initial, format_time, format_timestamp

api_bp = Blueprint("api", __name__)


@api_bp.before_request
def _require_login():
    """Reject unauthenticated API calls with a JSON 401."""
    if not session.get("user_id"):
        return jsonify({"error": "Authentication required."}), 401


def _get_db_helper() -> DatabaseHelper:
    """Helper to get DatabaseHelper from current app config."""
    path = current_app.config.get("DATABASE_PATH") or current_app.config.get("DB_PATH")
    return DatabaseHelper(Path(path))


@api_bp.route("/search")
def search():
    """Full-text search API — FTS5 paginated JSON results.

    Query parameters:
        q     : search query string (supports FTS5 syntax)
        page  : 1-based page number (default 1)
        limit : results per page, max 50 (default 20)
    """
    db_helper = _get_db_helper()
    raw_q = request.args.get("q", "").strip()

    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(50, max(1, int(request.args.get("limit", 20))))
    except (ValueError, TypeError):
        page = 1
        limit = 20

    if not raw_q:
        return jsonify({"results": [], "total": 0, "page": page, "limit": limit, "has_more": False, "query": ""})

    query_error = parse_search_query(raw_q).get_error()
    if query_error:
        return jsonify({"results": [], "total": 0, "page": page, "limit": limit,
                        "has_more": False, "query": raw_q, "error": query_error}), 400

    offset = (page - 1) * limit
    raw_results = search_messages(db_helper, query=raw_q, limit=limit, offset=offset)
    total = search_messages_count(db_helper, query=raw_q)

    enriched = []
    for r in raw_results:
        item = dict(r)
        item["formatted_time"] = format_timestamp(r.get("date"))
        item["avatar_color"] = avatar_color_index(r.get("address", ""))
        item["avatar_initial"] = avatar_initial(r.get("address", ""))
        enriched.append(item)

    has_more = (offset + len(enriched)) < total
    return jsonify({
        "results": enriched,
        "total": total,
        "page": page,
        "limit": limit,
        "has_more": has_more,
        "query": raw_q,
    })


@api_bp.route("/threads", methods=["GET"])
def threads():
    """Thread list API for pagination and infinite scroll."""
    db_helper = _get_db_helper()
    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(200, max(1, int(request.args.get("limit", 50))))
    except (ValueError, TypeError):
        page = 1
        limit = 50

    offset = (page - 1) * limit
    raw_threads = db_helper.get_threads(limit=limit, offset=offset)
    total = db_helper.get_threads_count()

    enriched_threads = []
    for t in raw_threads:
        addr = t.get("address", "")
        item = dict(t)
        item["formatted_time"] = format_timestamp(t.get("latest_date"))
        item["avatar_color"] = avatar_color_index(addr)
        item["avatar_initial"] = avatar_initial(addr)
        enriched_threads.append(item)

    has_more = (offset + len(enriched_threads)) < total
    return jsonify({
        "threads": enriched_threads,
        "total": total,
        "page": page,
        "limit": limit,
        "has_more": has_more,
    })


@api_bp.route("/messages/<path:address>", methods=["GET"])
def messages(address: str):
    """Paginated messages for a conversation thread."""
    db_helper = _get_db_helper()
    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(200, max(1, int(request.args.get("limit", 50))))
    except (ValueError, TypeError):
        page = 1
        limit = 50

    offset = (page - 1) * limit
    raw_messages = db_helper.get_messages_by_address(address, limit=limit, offset=offset)
    total = db_helper.get_messages_count_by_address(address)

    enriched_messages = []
    for m in raw_messages:
        item = dict(m)
        item["formatted_time"] = format_time(m.get("date"))
        enriched_messages.append(item)

    has_more = (offset + len(enriched_messages)) < total
    return jsonify({
        "messages": enriched_messages,
        "address": address,
        "total": total,
        "page": page,
        "limit": limit,
        "has_more": has_more,
    })


@api_bp.route("/import", methods=["POST"])
def import_sms():
    """ZIP/NDJSON import endpoint."""
    uploaded_file = request.files.get("file") or request.files.get("backup")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"error": "No file uploaded. Please select a .zip or .ndjson backup file."}), 400

    filename = uploaded_file.filename
    path = current_app.config.get("DATABASE_PATH") or current_app.config.get("DB_PATH")

    try:
        result = import_backup_file(uploaded_file.stream, filename, Path(path))
        return jsonify(result), 200
    except Exception as err:
        return jsonify({"error": f"Import failed: {str(err)}"}), 500


@api_bp.route("/import/history", methods=["GET"])
def import_history():
    """Retrieve import history log records."""
    path = current_app.config.get("DATABASE_PATH") or current_app.config.get("DB_PATH")
    try:
        history = get_import_history(Path(path))
        return jsonify({"history": history}), 200
    except Exception as err:
        return jsonify({"error": f"Failed to fetch import history: {str(err)}"}), 500


@api_bp.route("/export")
def export_sms():
    """Download messages in an optional ``from``/``to`` (YYYY-MM-DD) range as JSON."""
    try:
        start_ms, end_ms = parse_date_range(request.args.get("from"), request.args.get("to"))
    except ValueError as err:
        return jsonify({"error": f"Invalid date range: {err}"}), 400

    payload = export_to_json(_get_db_helper(), start_ms, end_ms)
    label = f"{request.args.get('from') or 'from-start'}_{request.args.get('to') or 'to-end'}"
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="sms_export_{label}.json"'},
    )


@api_bp.route("/export/count")
def export_count():
    """Number of messages in the selected range (export preview)."""
    try:
        start_ms, end_ms = parse_date_range(request.args.get("from"), request.args.get("to"))
    except ValueError as err:
        return jsonify({"error": f"Invalid date range: {err}"}), 400
    return jsonify({"count": count_messages(_get_db_helper(), start_ms, end_ms)})
