"""Tests for PWA support, Enter-only search page, and date: search filter."""

import json
from datetime import datetime

import pytest

from sms_viewer.app import create_app
from sms_viewer.database.db import init_db
from sms_viewer.database.db_helper import DatabaseHelper
from sms_viewer.feature.search import (
    parse_date_filter,
    parse_search_query,
    search_messages,
    search_messages_count,
)


def _ms(y, m, d, h=12):
    return int(datetime(y, m, d, h).timestamp() * 1000)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "d.db"
    init_db(path)
    helper = DatabaseHelper(path)
    rows = [
        ("HDFCBK", _ms(2024, 5, 20), "Your OTP is 111 for payment", "h1"),
        ("HDFCBK", _ms(2024, 5, 31, 23), "OTP 222 end of month", "h2"),
        ("AMAZON", _ms(2024, 6, 1, 0), "Your OTP is 333", "h3"),
        ("AMAZON", _ms(2023, 12, 25), "Christmas offer", "h4"),
    ]
    with helper.get_connection() as conn:
        for addr, date, body, h in rows:
            conn.execute(
                "INSERT INTO messages (address, date, body, body_hash) VALUES (?,?,?,?)",
                (addr, date, body, h),
            )
        conn.commit()
    return path


@pytest.fixture
def helper(db_path):
    return DatabaseHelper(db_path)


@pytest.fixture
def client(db_path):
    app = create_app(db_path=db_path, secret_key="k")
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = 1
    return c


# ---------------------------------------------------------------- date parsing

def test_parse_date_filter_granularity():
    s, e = parse_date_filter("2024-05-20")
    assert s == _ms(2024, 5, 20, 0)
    assert e - s == 24 * 3600 * 1000 - 1 or abs(e - s - 86399999) <= 3600 * 1000
    s, e = parse_date_filter("2024-05")
    assert s == _ms(2024, 5, 1, 0) and e >= _ms(2024, 5, 31, 23)
    s, e = parse_date_filter("2024")
    assert s == _ms(2024, 1, 1, 0) and e >= _ms(2024, 12, 31, 23)


def test_parse_date_filter_ranges():
    s, e = parse_date_filter("2024-05-01..2024-05-31")
    assert s == _ms(2024, 5, 1, 0) and e >= _ms(2024, 5, 31, 23)
    s, e = parse_date_filter("2024-05-01..")
    assert s is not None and e is None
    s, e = parse_date_filter("..2024-05-01")
    assert s is None and e is not None


@pytest.mark.parametrize("bad", ["abc", "2024-13", "2024-02-30", "2024-05-31..2024-05-01", "..", "24-05"])
def test_parse_date_filter_invalid(bad):
    with pytest.raises(ValueError):
        parse_date_filter(bad)


def test_parse_search_query_splits_text_and_date():
    p = parse_search_query("otp date:2024-05 address:HDFCBK")
    assert p.get_error() is None and p.has_date()
    assert p.get_text().split() == ["otp", "address:HDFCBK"]
    assert parse_search_query("plain").has_date() is False
    assert parse_search_query("date:nope").get_error()


# ---------------------------------------------------------------- date search

def test_date_only_search(helper):
    res = search_messages(helper, "date:2024-05")
    assert [r["address"] for r in res] == ["HDFCBK", "HDFCBK"]
    assert res[0]["date"] > res[1]["date"]
    assert search_messages_count(helper, "date:2024-05") == 2


def test_date_single_day_and_year(helper):
    assert search_messages_count(helper, "date:2024-05-20") == 1
    assert search_messages_count(helper, "date:2023") == 1
    assert search_messages_count(helper, "date:2024") == 3


def test_date_combined_with_text_and_column(helper):
    assert search_messages_count(helper, "otp date:2024-05") == 2
    assert search_messages_count(helper, "otp date:2024-06") == 1
    res = search_messages(helper, "address:HDFCBK date:2024-05-01..2024-05-25")
    assert len(res) == 1 and "111" in res[0]["body"]
    assert "<mark>" in search_messages(helper, "otp date:2024-05")[0]["snippet"]


def test_date_only_snippet_is_escaped(helper):
    with helper.get_connection() as conn:
        conn.execute(
            "INSERT INTO messages (address, date, body, body_hash) VALUES (?,?,?,?)",
            ("X", _ms(2022, 1, 1), "<script>alert(1)</script>", "hx"),
        )
        conn.commit()
    snippet = search_messages(helper, "date:2022")[0]["snippet"]
    assert "<script>" not in snippet and "&lt;script&gt;" in snippet


def test_invalid_date_returns_nothing(helper):
    assert search_messages(helper, "otp date:bogus") == []
    assert search_messages_count(helper, "date:bogus") == 0


def test_search_page_date_and_error(client):
    html = client.get("/search?q=date:2024-05").get_data(as_text=True)
    assert "2 results" in html
    err = client.get("/search?q=date:bogus").get_data(as_text=True)
    assert "Invalid date" in err


def test_api_search_date(client):
    data = client.get("/api/search?q=otp date:2024-06").get_json()
    assert data["total"] == 1
    bad = client.get("/api/search?q=date:bogus")
    assert bad.status_code == 400 and bad.get_json()["error"]


# ---------------------------------------------------- search page: Enter only

def test_search_page_has_no_autosearch(client):
    html = client.get("/search").get_data(as_text=True)
    assert "addEventListener('input'" not in html
    assert "setTimeout" not in html
    assert 'id="search-form"' in html


def test_home_page_live_filter_kept():
    js = open("src/sms_viewer/static/js/app.js").read()
    assert "searchInput.addEventListener('input'" in js


# ------------------------------------------------------------------------ PWA

def test_manifest_is_public_and_valid(db_path):
    app = create_app(db_path=db_path, secret_key="k")
    r = app.test_client().get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.mimetype == "application/manifest+json"
    m = json.loads(r.data)
    assert m["display"] == "standalone" and m["start_url"] == "/"
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(i["purpose"] == "maskable" for i in m["icons"])


def test_manifest_icons_exist(client):
    for icon in json.loads(client.get("/manifest.webmanifest").data)["icons"]:
        assert client.get(icon["src"]).status_code == 200


def test_service_worker_served_from_root(db_path):
    r = create_app(db_path=db_path, secret_key="k").test_client().get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.mimetype
    assert r.headers["Service-Worker-Allowed"] == "/"
    assert r.headers["Cache-Control"] == "no-cache"
    body = r.get_data(as_text=True)
    assert "/offline" in body and "/static/css/style.css" in body
    # private pages and API must never be cached
    assert "/api/" not in body.split("startsWith('/static/')")[0].split("fetch'")[-1]
    assert "request.mode" not in body and "req.mode === 'navigate'" in body


def test_offline_page_public(db_path):
    r = create_app(db_path=db_path, secret_key="k").test_client().get("/offline")
    assert r.status_code == 200 and "offline" in r.get_data(as_text=True).lower()


def test_pages_link_manifest_and_register_sw(client):
    html = client.get("/").get_data(as_text=True)
    assert 'rel="manifest"' in html and 'name="theme-color"' in html
    assert 'rel="apple-touch-icon"' in html
    assert "serviceWorker" in open("src/sms_viewer/static/js/app.js").read()
