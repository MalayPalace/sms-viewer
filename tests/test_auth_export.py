"""Tests for Phase 5: authentication, route protection, secret key, and export."""

import json
from datetime import datetime

import pytest

from sms_viewer.app import create_app
from sms_viewer.database.db import init_db
from sms_viewer.database.db_helper import DatabaseHelper
from sms_viewer.feature.exporter import count_messages, export_messages, parse_date_range


def _ms(y, m, d, h=12):
    return int(datetime(y, m, d, h).timestamp() * 1000)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "auth.db"
    init_db(path)
    helper = DatabaseHelper(path)
    rows = [
        ("a1", "t1", "+100", _ms(2024, 5, 1), 1, "first", "h1"),
        ("a2", "t1", "+100", _ms(2024, 5, 2, 23), 2, "second", "h2"),
        ("a3", "t2", "BANK", _ms(2024, 5, 10), 1, "third", "h3"),
    ]
    with helper.get_connection() as conn:
        for oid, tid, addr, date, typ, body, h in rows:
            conn.execute(
                "INSERT INTO messages (original_id, thread_id, address, date, type, body, body_hash)"
                " VALUES (?,?,?,?,?,?,?)",
                (oid, tid, addr, date, typ, body, h),
            )
        conn.commit()
    return path


@pytest.fixture
def anon_client(db_path):
    app = create_app(db_path=db_path, secret_key="k")
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def client(anon_client):
    with anon_client.session_transaction() as s:
        s["user_id"] = 1
    return anon_client


def _post(client, url, **data):
    """POST a form with the CSRF token scraped from the rendered page, like a browser."""
    html = client.get(url if url != "/logout" else "/login").get_data(as_text=True)
    marker = 'name="csrf_token" value="'
    token = html.split(marker)[1].split('"')[0] if marker in html else ""
    return client.post(url, data={**data, "csrf_token": token})


def test_setup_login_logout_flow(anon_client):
    assert anon_client.get("/login").headers["Location"].endswith("/setup")
    r = _post(anon_client, "/setup", username="u", password="short", confirm_password="short")
    assert b"at least 8" in r.data
    r = _post(anon_client, "/setup", username="u", password="password1", confirm_password="nope")
    assert b"do not match" in r.data
    r = _post(anon_client, "/setup", username="u", password="password1", confirm_password="password1")
    assert r.status_code == 302
    assert anon_client.get("/setup").headers["Location"].endswith("/login")

    r = _post(anon_client, "/login", username="u", password="wrong")
    assert b"Invalid username or password" in r.data
    r = _post(anon_client, "/login", username="u", password="password1")
    assert r.status_code == 302
    assert anon_client.get("/").status_code == 200

    with anon_client.session_transaction() as s:
        s["csrf_token"] = "tok"
    anon_client.post("/logout", data={"csrf_token": "tok"})
    assert anon_client.get("/").status_code == 302


@pytest.mark.parametrize("url", ["/", "/thread/+100", "/search?q=x", "/import", "/export"])
def test_pages_require_login(anon_client, url):
    r = anon_client.get(url)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"] or "/setup" in r.headers["Location"]


@pytest.mark.parametrize("url", [
    "/api/threads", "/api/messages/+100", "/api/search?q=x", "/api/import/history",
    "/api/export", "/api/export/count",
])
def test_api_requires_login(anon_client, url):
    r = anon_client.get(url)
    assert r.status_code == 401
    assert r.get_json()["error"]


def test_import_api_requires_login(anon_client):
    with anon_client.session_transaction() as s:
        s["csrf_token"] = "tok"
    assert anon_client.post("/api/import", headers={"X-CSRFToken": "tok"}).status_code == 401


def test_secret_key_persisted(db_path, monkeypatch):
    monkeypatch.delenv("SMS_VIEWER_SECRET", raising=False)
    key1 = create_app(db_path=db_path).config["SECRET_KEY"]
    key2 = create_app(db_path=db_path).config["SECRET_KEY"]
    assert key1 == key2 and len(key1) == 64
    assert ((db_path.parent / ".secret_key").stat().st_mode & 0o777) == 0o600


def test_secret_key_env_and_explicit(db_path, monkeypatch):
    monkeypatch.setenv("SMS_VIEWER_SECRET", "envkey")
    assert create_app(db_path=db_path).config["SECRET_KEY"] == "envkey"
    assert create_app(db_path=db_path, secret_key="x").config["SECRET_KEY"] == "x"


def test_parse_date_range():
    assert parse_date_range(None, None) == (None, None)
    s, e = parse_date_range("2024-05-01", "2024-05-01")
    assert e - s == 24 * 3600 * 1000 - 1 or abs((e - s) - 86399999) <= 3600 * 1000
    with pytest.raises(ValueError):
        parse_date_range("bad", None)
    with pytest.raises(ValueError):
        parse_date_range("2024-05-02", "2024-05-01")


def test_exporter_range(db_path):
    helper = DatabaseHelper(db_path)
    assert export_messages(helper, None, None)["count"] == 3
    s, e = parse_date_range("2024-05-02", "2024-05-02")
    doc = export_messages(helper, s, e)
    assert [m["body"] for m in doc["messages"]] == ["second"]
    assert count_messages(helper, *parse_date_range("2024-05-01", "2024-05-02")) == 2
    assert set(doc["messages"][0]) >= {"address", "date", "type", "body", "read"}


def test_export_api_download(client):
    r = client.get("/api/export?from=2024-05-01&to=2024-05-02")
    assert r.status_code == 200
    assert "attachment" in r.headers["Content-Disposition"]
    assert r.headers["Content-Disposition"].endswith('.json"')
    data = json.loads(r.data)
    assert data["count"] == 2
    assert [m["body"] for m in data["messages"]] == ["first", "second"]


def test_export_api_validation_and_count(client):
    assert client.get("/api/export?from=garbage").status_code == 400
    assert client.get("/api/export/count?from=2024-05-09&to=2024-05-01").status_code == 400
    assert client.get("/api/export/count").get_json()["count"] == 3
    assert client.get("/api/export/count?from=2024-05-10").get_json()["count"] == 1


def test_export_page_ui(client):
    html = client.get("/export").get_data(as_text=True)
    assert 'name="from"' in html and 'name="to"' in html
    assert "/api/export" in html and "Phase 5" not in html
