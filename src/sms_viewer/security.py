"""
Security hardening for SMS Viewer: CSRF protection, response headers and
a small in-memory login rate limiter.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import defaultdict, deque

from flask import Flask, abort, current_app, request, session

CSRF_SESSION_KEY = "csrf_token"
CSRF_HEADER = "X-CSRFToken"
CSRF_FIELD = "csrf_token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def generate_csrf_token() -> str:
    """Return the session's CSRF token, creating it on first use."""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_hex(32)
        session[CSRF_SESSION_KEY] = token
    return token


def _validate_csrf() -> None:
    if request.method in SAFE_METHODS or not current_app.config.get("CSRF_ENABLED", True):
        return
    expected = session.get(CSRF_SESSION_KEY, "")
    supplied = request.headers.get(CSRF_HEADER) or request.form.get(CSRF_FIELD, "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        abort(403, description="Invalid or missing CSRF token.")


def _add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Content-Security-Policy", CSP)
    if request.path.startswith(("/api/", "/login", "/setup")):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def init_security(app: Flask) -> None:
    """Register CSRF checks, security headers and hardened cookie settings."""
    app.config.setdefault("CSRF_ENABLED", True)
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    # Flask pre-populates these keys with None, so setdefault would be a no-op
    if app.config.get("SESSION_COOKIE_SAMESITE") is None:
        app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if app.config.get("MAX_CONTENT_LENGTH") is None:
        app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024
    app.config.setdefault("LOGIN_MAX_ATTEMPTS", 5)
    app.config.setdefault("LOGIN_WINDOW_SECONDS", 300)

    app.before_request(_validate_csrf)
    app.after_request(_add_security_headers)
    app.jinja_env.globals["csrf_token"] = generate_csrf_token


class LoginRateLimiter:
    """Sliding-window limiter on failed logins, keyed by client address."""

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, window: float, now: float) -> deque[float]:
        q = self._failures[key]
        while q and now - q[0] > window:
            q.popleft()
        return q

    def retry_after(self, key: str, max_attempts: int, window: float) -> int:
        """Seconds until another attempt is allowed (0 when not blocked)."""
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, window, now)
            if len(q) < max_attempts:
                return 0
            return max(1, int(window - (now - q[0])) + 1)

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._failures[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
