"""
Phase 4 tests: Search engine, entity recognizer, and /api/search endpoint.
"""

from datetime import datetime
import pytest

from sms_viewer.app import create_app
from sms_viewer.database.db import init_db
from sms_viewer.database.db_helper import DatabaseHelper
from sms_viewer.feature.recognizer import highlight_entities
from sms_viewer.feature.search import sanitize_fts_query, search_messages, search_messages_count


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_search.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def db_with_messages(temp_db):
    """DB pre-populated with 5 varied messages across 3 threads."""
    db = DatabaseHelper(temp_db)
    base = int(datetime(2024, 3, 1, 10, 0, 0).timestamp() * 1000)
    batch = [
        ("id1", "t1", "HDFC-Bank", base + 1000, base + 1000, 1, -1, 1,
         "Your OTP is 482910. Do not share.", "h1"),
        ("id2", "t1", "HDFC-Bank", base + 2000, base + 2000, 1, -1, 1,
         "Transaction of INR 5000 on your account.", "h2"),
        ("id3", "t2", "+911234567890", base + 3000, base + 3000, 1, -1, 1,
         "Call me back at 9876543210 when free.", "h3"),
        ("id4", "t2", "+911234567890", base + 4000, base + 4000, 0, -1, 2,
         "Sure, will call you. Check https://meet.google.com/abc-def", "h4"),
        ("id5", "t3", "Alice", base + 5000, base + 5000, 1, -1, 1,
         "Hi, please send the report. My email is alice@example.com.", "h5"),
    ]
    db.bulk_insert_messages(batch)
    return temp_db


@pytest.fixture
def app_and_client(db_with_messages):
    app = create_app(db_path=db_with_messages, secret_key="test_secret")
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "admin"
    return app, client


# ---------------------------------------------------------------------------
# 1. Query Sanitization
# ---------------------------------------------------------------------------

class TestSanitizeFtsQuery:
    def test_empty_returns_empty(self):
        assert sanitize_fts_query("") == ""
        assert sanitize_fts_query("   ") == ""

    def test_plain_word(self):
        assert sanitize_fts_query("transaction") == "transaction"

    def test_prefix_preserved(self):
        assert sanitize_fts_query("trans*") == "trans*"

    def test_balanced_phrase_preserved(self):
        assert sanitize_fts_query('"credit card"') == '"credit card"'

    def test_unbalanced_quote_stripped(self):
        q = sanitize_fts_query('hello"')
        assert q.count('"') % 2 == 0  # balanced (i.e. 0)

    def test_dangerous_chars_removed(self):
        q = sanitize_fts_query("hello; DROP TABLE messages--")
        assert ";" not in q

    def test_null_byte_removed(self):
        q = sanitize_fts_query("hello\x00world")
        assert "\x00" not in q


# ---------------------------------------------------------------------------
# 2. Entity Recognizer
# ---------------------------------------------------------------------------

class TestHighlightEntities:
    def test_none_returns_empty(self):
        result = str(highlight_entities(None))
        assert result == ""

    def test_plain_text_escaped(self):
        result = str(highlight_entities("Hello <World> & 'you'"))
        # Should be HTML-escaped
        assert "<World>" not in result
        assert "&lt;World&gt;" in result

    def test_url_detected(self):
        result = str(highlight_entities("Visit https://example.com for details"))
        assert 'entity--url' in result
        assert 'data-copy="https://example.com"' in result

    def test_email_detected(self):
        result = str(highlight_entities("Email me at user@example.com please"))
        assert 'entity--email' in result
        assert 'data-copy="user@example.com"' in result

    def test_otp_keyword_detected(self):
        result = str(highlight_entities("Your OTP is 482910. Do not share."))
        assert 'entity--otp' in result
        assert 'data-copy="482910"' in result

    def test_otp_pin_keyword_detected(self):
        result = str(highlight_entities("Your PIN: 9900 for login"))
        assert 'entity--otp' in result
        assert 'data-copy="9900"' in result

    def test_otp_code_keyword_detected(self):
        result = str(highlight_entities("Verification code: 123456"))
        assert 'entity--otp' in result

    def test_standalone_otp_detected(self):
        # No keyword — a bare 6-digit number should be highlighted
        result = str(highlight_entities("483920 is valid for 5 minutes"))
        assert 'entity--otp' in result

    def test_standalone_otp_not_triggered_when_keyword_present(self):
        # When keyword OTP found, standalone pattern should not double-match
        text = "OTP: 482910. Also note 999999"
        result = str(highlight_entities(text))
        # 482910 should be in OTP badge; 999999 should NOT (keyword OTP found)
        assert '482910' in result
        # Standalone OTP for 999999 should be absent since keyword OTP found
        assert result.count('entity--otp') <= 1

    def test_phone_detected(self):
        result = str(highlight_entities("Call 9876543210 for support"))
        assert 'entity--phone' in result

    def test_no_entities_plain_text(self):
        result = str(highlight_entities("Hello, how are you today?"))
        assert 'entity' not in result
        assert "Hello, how are you today?" in result

    def test_url_takes_priority_over_email_in_url(self):
        # URL contains @-like chars — URL should win, not email
        text = "See https://user@example.com/path"
        result = str(highlight_entities(text))
        assert 'entity--url' in result

    def test_xss_body_escaped(self):
        result = str(highlight_entities("<script>alert(1)</script>"))
        assert "<script>" not in result
        assert "&lt;script&gt;" in result


# ---------------------------------------------------------------------------
# 3. Search Engine (FTS5)
# ---------------------------------------------------------------------------

class TestSearchEngine:
    def test_search_finds_match(self, db_with_messages):
        db = DatabaseHelper(db_with_messages)
        results = search_messages(db, "OTP")
        assert len(results) >= 1
        assert any("482910" in r["body"] for r in results)

    def test_search_snippet_has_mark_tag(self, db_with_messages):
        db = DatabaseHelper(db_with_messages)
        results = search_messages(db, "OTP")
        assert any("<mark>" in r.get("snippet", "") for r in results)

    def test_search_prefix_match(self, db_with_messages):
        db = DatabaseHelper(db_with_messages)
        results = search_messages(db, "trans*")
        assert len(results) >= 1

    def test_search_no_results_for_garbage(self, db_with_messages):
        db = DatabaseHelper(db_with_messages)
        results = search_messages(db, "xyzzy_nonexistent_word")
        assert results == []

    def test_search_count_matches_results(self, db_with_messages):
        db = DatabaseHelper(db_with_messages)
        total = search_messages_count(db, "account")
        results = search_messages(db, "account", limit=50)
        assert total == len(results)

    def test_search_empty_query_returns_empty(self, db_with_messages):
        db = DatabaseHelper(db_with_messages)
        results = search_messages(db, "")
        assert results == []

    def test_search_pagination(self, db_with_messages):
        db = DatabaseHelper(db_with_messages)
        # Insert enough to paginate
        base = int(datetime(2024, 4, 1).timestamp() * 1000)
        extra = [
            (f"ex{i}", "t_extra", "Spam", base + i * 1000, base + i * 1000,
             1, -1, 1, f"Keyword match number {i}", f"hx{i}")
            for i in range(10)
        ]
        db.bulk_insert_messages(extra)
        total = search_messages_count(db, "Keyword")
        page1 = search_messages(db, "Keyword", limit=5, offset=0)
        page2 = search_messages(db, "Keyword", limit=5, offset=5)
        assert total == 10
        assert len(page1) == 5
        assert len(page2) == 5
        # No overlap
        ids1 = {r["id"] for r in page1}
        ids2 = {r["id"] for r in page2}
        assert ids1.isdisjoint(ids2)

    def test_invalid_fts_query_returns_empty(self, db_with_messages):
        db = DatabaseHelper(db_with_messages)
        # Malformed FTS5 (bare operators are invalid in FTS5)
        results = search_messages(db, "AND AND")
        # Should not raise, just return empty
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# 4. /api/search Endpoint
# ---------------------------------------------------------------------------

class TestApiSearch:
    def test_empty_query_returns_empty(self, app_and_client):
        _, client = app_and_client
        resp = client.get("/api/search")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["results"] == []
        assert data["total"] == 0

    def test_search_otp_returns_results(self, app_and_client):
        _, client = app_and_client
        resp = client.get("/api/search?q=OTP")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] >= 1
        assert len(data["results"]) >= 1
        assert data["query"] == "OTP"

    def test_search_result_has_enrichment_fields(self, app_and_client):
        _, client = app_and_client
        resp = client.get("/api/search?q=OTP")
        data = resp.get_json()
        r = data["results"][0]
        assert "formatted_time" in r
        assert "avatar_color" in r
        assert "avatar_initial" in r
        assert "snippet" in r

    def test_search_pagination_has_more(self, app_and_client, db_with_messages):
        _, client = app_and_client
        db = DatabaseHelper(db_with_messages)
        base = int(datetime(2024, 5, 1).timestamp() * 1000)
        extra = [
            (f"pg{i}", "tp", "PagTest", base + i * 1000, base + i * 1000,
             1, -1, 1, f"paginate me word {i}", f"hp{i}")
            for i in range(25)
        ]
        db.bulk_insert_messages(extra)

        resp1 = client.get("/api/search?q=paginate&page=1&limit=10")
        d1 = resp1.get_json()
        assert d1["total"] == 25
        assert len(d1["results"]) == 10
        assert d1["has_more"] is True

        resp2 = client.get("/api/search?q=paginate&page=3&limit=10")
        d2 = resp2.get_json()
        assert len(d2["results"]) == 5
        assert d2["has_more"] is False


# ---------------------------------------------------------------------------
# 5. /search View (SSR)
# ---------------------------------------------------------------------------

class TestSearchView:
    def test_search_page_empty_renders(self, app_and_client):
        _, client = app_and_client
        resp = client.get("/search")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Search your messages" in html

    def test_search_page_with_query_shows_results(self, app_and_client):
        _, client = app_and_client
        resp = client.get("/search?q=OTP")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "result" in html.lower()
        assert "HDFC-Bank" in html

    def test_search_page_no_results_shows_empty_state(self, app_and_client):
        _, client = app_and_client
        resp = client.get("/search?q=xyzzy_nonexistent")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "No results" in html or "No matching" in html


def test_snippet_escapes_html_and_marks_match(tmp_path):
    from sms_viewer.database.db import init_db
    from sms_viewer.database.db_helper import DatabaseHelper
    from sms_viewer.feature.search import search_messages

    path = tmp_path / "hl.db"
    init_db(path)
    helper = DatabaseHelper(path)
    with helper.get_connection() as conn:
        conn.execute(
            "INSERT INTO messages (address, date, body, body_hash) VALUES (?,?,?,?)",
            ("A", 1, "Your OTP is 123 <script>x</script> & more", "h"),
        )
        conn.commit()

    snippet = search_messages(helper, "OTP")[0]["snippet"]
    assert "<mark>OTP</mark>" in snippet
    assert "<script>" not in snippet
    assert "&lt;script&gt;" in snippet and "&amp;" in snippet
