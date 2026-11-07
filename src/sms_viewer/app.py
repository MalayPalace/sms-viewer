"""
Flask application factory for SMS Viewer.

Configures application settings, initializes database schemas, and registers blueprints
from rest and views subpackages.
"""

import os
import secrets
from pathlib import Path

from flask import Flask, render_template

from sms_viewer.database import close_db, init_db, resolve_db_path
from sms_viewer.rest import api_bp, auth_bp
from sms_viewer.views import views_bp
from sms_viewer.utils import avatar_color_index, avatar_initial, format_date_label, format_time, format_timestamp
from sms_viewer.feature.recognizer import highlight_entities


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
        is generated (non-persistent across restarts).
    """
    app = Flask(__name__)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    resolved_db: Path = db_path if db_path is not None else resolve_db_path()
    app.config["DATABASE_PATH"] = resolved_db
    app.config["DB_PATH"] = resolved_db

    # Secret key — used to sign session cookies
    _secret = (
        secret_key
        or os.environ.get("SMS_VIEWER_SECRET")
        or secrets.token_hex(32)
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
    # Error handlers
    # ------------------------------------------------------------------
    @app.errorhandler(404)
    def not_found(e):  # noqa: ANN001, ANN202
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):  # noqa: ANN001, ANN202
        return render_template("errors/500.html"), 500

    return app
