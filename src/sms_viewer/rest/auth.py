"""
Authentication blueprint for SMS Viewer.

Provides setup, login, logout routes and login_required authorization wrapper
using DatabaseHelper for authentication queries.
"""

from functools import wraps

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from sms_viewer.database.db_helper import DatabaseHelper
from sms_viewer.security import LoginRateLimiter

MAX_USERNAME_LEN = 64
MAX_PASSWORD_LEN = 256

_limiter = LoginRateLimiter()

auth_bp = Blueprint("auth", __name__)


def _get_db_helper() -> DatabaseHelper:
    """Obtain DatabaseHelper for current application configuration."""
    path = current_app.config.get("DATABASE_PATH") or current_app.config.get("DB_PATH")
    return DatabaseHelper(path)


# ---------------------------------------------------------------------------
# Login-required decorator
# ---------------------------------------------------------------------------

def login_required(f):
    """Redirect unauthenticated requests to the login page."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@auth_bp.route("/setup", methods=["GET", "POST"])
def setup():
    """First-run setup: create the initial user account."""
    db_helper = _get_db_helper()

    # If a user already exists, skip setup
    if db_helper.has_any_user():
        return redirect(url_for("auth.login"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not username:
            error = "Username is required."
        elif not password:
            error = "Password is required."
        elif len(username) > MAX_USERNAME_LEN:
            error = f"Username must be at most {MAX_USERNAME_LEN} characters."
        elif len(password) > MAX_PASSWORD_LEN:
            error = f"Password must be at most {MAX_PASSWORD_LEN} characters."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            try:
                db_helper.create_user(username, generate_password_hash(password))
                flash("Account created! Please log in.", "success")
                return redirect(url_for("auth.login"))
            except Exception:  # noqa: BLE001
                error = "Failed to create account. Please try again."

    return render_template("auth/setup.html", error=error)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Log in with username and password."""
    db_helper = _get_db_helper()

    # Redirect to setup if no user exists yet
    if not db_helper.has_any_user():
        return redirect(url_for("auth.setup"))

    # Already logged in
    if session.get("user_id"):
        return redirect(url_for("views.threads"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        client = request.remote_addr or "unknown"
        max_attempts = current_app.config["LOGIN_MAX_ATTEMPTS"]
        window = current_app.config["LOGIN_WINDOW_SECONDS"]
        wait = _limiter.retry_after(client, max_attempts, window)
        if wait:
            error = f"Too many failed attempts. Try again in {wait} seconds."
            return render_template("auth/login.html", error=error), 429

        user = db_helper.get_user_by_username(username)

        if user is None or not check_password_hash(user["password_hash"], password):
            _limiter.record_failure(client)
            error = "Invalid username or password."
        else:
            _limiter.reset(client)
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = username
            return redirect(url_for("views.threads"))

    return render_template("auth/login.html", error=error)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Clear the session and redirect to login."""
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
