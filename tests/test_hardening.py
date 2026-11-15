"""Tests for Phase 6: error handling, CSRF, rate limiting, headers, accessibility."""

import pytest

from sms_viewer.app import create_app
from sms_viewer.database.db import init_db
from sms_viewer.database.db_helper import DatabaseHelper
from sms_viewer.rest import auth as auth_module
from werkzeug.security import generate_password_hash


@pytest.fixture
def app(tmp_path):
    path = tmp_path / "h.db"
    init_db(path)
    DatabaseHelper(path).create_user("user", generate_password_hash("password1"))
    application = create_app(db_path=path, secret_key="k")
    application.config["TESTING"] = True
    auth_module._limiter = auth_module.LoginRateLimiter()
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in(client):
    with client.session_transaction() as s:
        s["user_id"] = 1
        s["csrf_token"] = "tok"
    return client


def test_404_html_page(logged_in):
    r = logged_in.get("/no/such/page")
    assert r.status_code == 404
    assert "Page not found" in r.get_data(as_text=True)


def test_404_api_is_json(logged_in):
    r = logged_in.get("/api/nope")
    assert r.status_code == 404
    assert r.get_json()["error"]


def test_405_is_handled(logged_in):
    r = logged_in.post("/health", headers={"X-CSRFToken": "tok"})
    assert r.status_code == 405
    assert "Method not allowed" in r.get_data(as_text=True)


def test_500_page_and_no_leak(app):
    app.config["PROPAGATE_EXCEPTIONS"] = False
    app.config["TESTING"] = False

    @app.route("/boom")
    def boom():
        raise RuntimeError("secret detail")

    r = app.test_client().get("/boom")
    body = r.get_data(as_text=True)
    assert r.status_code == 500
    assert "Something went wrong" in body and "secret detail" not in body


def test_csrf_blocks_post_without_token(client):
    r = client.post("/login", data={"username": "user", "password": "password1"})
    assert r.status_code == 403


def test_csrf_blocks_wrong_token(logged_in):
    r = logged_in.post("/logout", data={"csrf_token": "bad"})
    assert r.status_code == 403


def test_csrf_accepts_form_and_header_token(logged_in):
    assert logged_in.post("/logout", data={"csrf_token": "tok"}).status_code == 302
    with logged_in.session_transaction() as s:
        s["csrf_token"] = "tok"
    r = logged_in.post("/api/import", headers={"X-CSRFToken": "tok"})
    assert r.status_code == 401 or r.status_code == 400


def test_upload_limit_configured(app):
    assert app.config["MAX_CONTENT_LENGTH"]


def test_csrf_api_json_error(client):
    r = client.post("/api/import")
    assert r.status_code == 403 and r.get_json()["error"]


def test_csrf_token_rendered_in_forms(client):
    html = client.get("/login").get_data(as_text=True)
    assert 'name="csrf_token"' in html and 'name="csrf-token"' in html


def test_csrf_can_be_disabled(app):
    app.config["CSRF_ENABLED"] = False
    r = app.test_client().post("/login", data={"username": "user", "password": "password1"})
    assert r.status_code == 302


def _login(client, password):
    html = client.get("/login").get_data(as_text=True)
    token = html.split('name="csrf_token" value="')[1].split('"')[0]
    return client.post("/login", data={"username": "user", "password": password, "csrf_token": token})


def test_login_rate_limit(app, client):
    app.config["LOGIN_MAX_ATTEMPTS"] = 3
    for _ in range(3):
        assert _login(client, "wrong").status_code == 200
    r = _login(client, "password1")
    assert r.status_code == 429
    assert "Too many failed attempts" in r.get_data(as_text=True)


def test_successful_login_resets_counter(app, client):
    app.config["LOGIN_MAX_ATTEMPTS"] = 3
    _login(client, "wrong")
    _login(client, "wrong")
    assert _login(client, "password1").status_code == 302
    client.get("/logout")
    with client.session_transaction() as s:
        s.clear()
    assert _login(client, "wrong").status_code == 200


def test_setup_rejects_overlong_input(tmp_path):
    path = tmp_path / "s.db"
    init_db(path)
    application = create_app(db_path=path, secret_key="k")
    c = application.test_client()
    html = c.get("/setup").get_data(as_text=True)
    token = html.split('name="csrf_token" value="')[1].split('"')[0]
    r = c.post("/setup", data={
        "username": "u" * 100, "password": "password1",
        "confirm_password": "password1", "csrf_token": token,
    })
    assert b"at most" in r.data


def test_security_headers_and_cookie_flags(client):
    r = client.get("/login")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert "HttpOnly" in r.headers.get("Set-Cookie", "")
    assert "SameSite=Lax" in r.headers.get("Set-Cookie", "")


def test_accessibility_markup(logged_in):
    html = logged_in.get("/").get_data(as_text=True)
    assert "user-scalable=no" not in html
    assert 'class="skip-link"' in html and 'id="main-content"' in html
