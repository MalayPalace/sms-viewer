"""
Flask application factory for SMS Viewer.

All configuration lives here. Blueprints are registered as they are
implemented in later phases. Phase 1 wires up the DB teardown and
exposes a minimal health-check route so the server can be verified.
"""

import os
import secrets
from pathlib import Path

from flask import Flask, render_template

from sms_viewer.api import api_bp
from sms_viewer.auth import auth_bp
from sms_viewer.db import close_db, init_db, resolve_db_path
from sms_viewer.views import views_bp


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
        is generated (non-persistent across restarts — fine for dev, but
        set the env var for production so sessions survive server restarts).
    """
    app = Flask(__name__)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    # Use the path as-is if already resolved by the caller (CLI), otherwise
    # fall back to resolving from env var / default location.
    # resolved_db: Path = db_path if db_path is not None else resolve_db_path()
    app.config["DATABASE_PATH"] = db_path

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
    init_db(db_path)

    # Register DB connection teardown for every request context
    app.teardown_appcontext(close_db)

    # ------------------------------------------------------------------
    # Blueprints
    # ------------------------------------------------------------------
    app.register_blueprint(auth_bp)
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    # ------------------------------------------------------------------
    # Health-check endpoint
    # ------------------------------------------------------------------
    @app.route("/health")
    def health():  # noqa: ANN202
        """Lightweight health-check endpoint."""
        return {"status": "ok", "db": str(db_path)}, 200

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
