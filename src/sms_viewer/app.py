"""
Flask application factory for SMS Viewer.

Configures application settings, initializes database schemas, and registers blueprints
from rest and views subpackages.
"""

import os
import secrets
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from sms_viewer.database import close_db, init_db, resolve_db_path
from sms_viewer.rest import api_bp, auth_bp
from sms_viewer.views import views_bp
from sms_viewer.utils import avatar_color_index, avatar_initial, format_date_label, format_time, format_timestamp
from sms_viewer.feature.recognizer import highlight_entities
from sms_viewer.pwa import pwa_bp
from sms_viewer.security import init_security


def _load_or_create_secret(path: Path) -> str:
    """Return the persisted secret key, generating it (mode 0600) on first use."""
    try:
        existing = path.read_text().strip()
        if existing:
            return existing
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(key)
    except OSError:
        pass  # read-only location: fall back to a non-persistent key
    return key


def create_app(db_path: Path | None = None, secret_key: str | None = None) -> Flask:
    """Create and configure the Flask application.

    Parameters
    ----------
    db_path:
        Already-resolved absolute ``Path`` to the SQLite database file.
        When *None*, ``resolve_db_path()`` is called here as a fallback
        (e.g. when invoking ``create_app()`` directly in tests without a CLI).
    secret_key:
        Flask secret key for session signing. When *None* it is read from
        ``SMS_VIEWER_SECRET`` env var; if that is also absent a random key
        is generated and stored in ``.secret_key`` beside the database.
    """
    app = Flask(__name__)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    resolved_db: Path = Path(db_path) if db_path is not None else resolve_db_path()
    app.config["DATABASE_PATH"] = resolved_db
    app.config["DB_PATH"] = resolved_db

    # Secret key — used to sign session cookies
    _secret = (
        secret_key
        or os.environ.get("SMS_VIEWER_SECRET")
        or _load_or_create_secret(resolved_db.parent / ".secret_key")
    )
    app.config["SECRET_KEY"] = _secret

    # ------------------------------------------------------------------
    # Database initialisation
    # ------------------------------------------------------------------
    init_db(resolved_db)

    # Register DB connection teardown for request context
    app.teardown_appcontext(close_db)

    # ------------------------------------------------------------------
    # Blueprints
    # ------------------------------------------------------------------
    app.register_blueprint(auth_bp)
    app.register_blueprint(views_bp)
    app.register_blueprint(pwa_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    # ------------------------------------------------------------------
    # Template filters
    # ------------------------------------------------------------------
    app.template_filter("format_timestamp")(format_timestamp)
    app.template_filter("format_time")(format_time)
    app.template_filter("format_date_label")(format_date_label)
    app.template_filter("avatar_color_index")(avatar_color_index)
    app.template_filter("avatar_initial")(avatar_initial)
    app.template_filter("highlight_entities")(highlight_entities)

    # ------------------------------------------------------------------
    # Health-check endpoint
    # ------------------------------------------------------------------
    @app.route("/health")
    def health():  # noqa: ANN202
        """Lightweight health-check endpoint."""
        return {"status": "ok", "db": str(resolved_db)}, 200

    # ------------------------------------------------------------------
    # Security hardening (CSRF, headers, cookies, rate limiting config)
    # ------------------------------------------------------------------
    init_security(app)
    app.config.setdefault("SEND_FILE_MAX_AGE_DEFAULT", 86400)

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------
    _error_titles = {
        400: "Bad request",
        403: "Forbidden",
        404: "Page not found",
        405: "Method not allowed",
        413: "File too large",
        429: "Too many requests",
        500: "Something went wrong",
    }

    def _handle_error(e):  # noqa: ANN001, ANN202
        code = getattr(e, "code", 500) or 500
        title = _error_titles.get(code, "Error")
        message = {
            404: "The page you are looking for does not exist.",
            500: "An unexpected error occurred. Please try again.",
        }.get(code) or getattr(e, "description", None) or title
        if request.path.startswith("/api/"):
            return jsonify({"error": message}), code
        template = f"errors/{code}.html" if code in (404, 500) else "errors/error.html"
        return render_template(template, code=code, title=title, message=message), code

    for _code in _error_titles:
        app.register_error_handler(_code, _handle_error)

    return app
