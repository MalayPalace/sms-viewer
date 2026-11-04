"""
Unit and integration tests for Phase 3: Thread Views & UI, Pagination APIs, and Formatters.
"""

from datetime import datetime, timedelta
import pytest

from sms_viewer.app import create_app
from sms_viewer.database.db import init_db
from sms_viewer.database.db_helper import DatabaseHelper
from sms_viewer.utils import (
    avatar_color_index,
    avatar_initial,
    format_date_label,
    format_time,
    format_timestamp,
    group_messages_by_date,
)


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_views.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def app_and_client(temp_db):
    app = create_app(db_path=temp_db, secret_key="test_secret")
    app.config["TESTING"] = True
    client = app.test_client()

    # Simulate authenticated session
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "admin"

    return app, client


def test_utils_formatting():
    # Fixed timestamp: 2026-09-12 10:30:00 (approx 1789209000000 ms)
    dt = datetime(2024, 5, 20, 14, 30, 0)
    epoch_ms = int(dt.timestamp() * 1000)

    # Format time
    formatted_t = format_time(epoch_ms)
    assert "2:30 PM" in formatted_t

    # Format date label
    date_lbl = format_date_label(epoch_ms)
    assert "May 20" in date_lbl

    # Avatar helpers
    assert avatar_color_index("Alice") == avatar_color_index("Alice")
    assert 0 <= avatar_color_index("Bob") <= 7
    assert avatar_initial("+1234567") == "1"
    assert avatar_initial("HDFC-BANK") == "H"
    assert avatar_initial("") == "#"


def test_group_messages_by_date():
    t1 = int(datetime(2024, 1, 10, 10, 0, 0).timestamp() * 1000)
    t2 = int(datetime(2024, 1, 10, 11, 0, 0).timestamp() * 1000)
    t3 = int(datetime(2024, 1, 11, 9, 0, 0).timestamp() * 1000)

    msgs = [
        {"id": 1, "date": t1, "body": "Msg 1"},
        {"id": 2, "date": t2, "body": "Msg 2"},
        {"id": 3, "date": t3, "body": "Msg 3"},
    ]

    groups = group_messages_by_date(msgs)
    assert len(groups) == 2
    assert len(groups[0][1]) == 2
    assert len(groups[1][1]) == 1


def test_threads_view_empty(app_and_client):
    _, client = app_and_client
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "No messages yet" in html
    assert "Import an SMS backup file" in html


def test_threads_view_populated(app_and_client, temp_db):
    db_helper = DatabaseHelper(temp_db)

    # Populate 2 threads
    t_older = int(datetime(2024, 1, 1, 10, 0, 0).timestamp() * 1000)
    t_newer = int(datetime(2024, 1, 2, 10, 0, 0).timestamp() * 1000)

    batch = [
        ("orig_1", "t1", "Alice", t_older, t_older, 1, -1, 1, "Hello from Alice", "hash1"),
        ("orig_2", "t2", "Bob", t_newer, t_newer, 0, -1, 1, "Urgent from Bob", "hash2"),
    ]
    db_helper.bulk_insert_messages(batch)

    _, client = app_and_client
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Both senders present
    assert "Alice" in html
    assert "Bob" in html
    # Bob has unread message
    assert "thread-item--unread" in html
    # Bob is newer, should appear before Alice
    bob_idx = html.find("Bob")
    alice_idx = html.find("Alice")
    assert bob_idx < alice_idx


def test_conversation_view_and_mark_read(app_and_client, temp_db):
    db_helper = DatabaseHelper(temp_db)

    t1 = int(datetime(2024, 1, 1, 10, 0, 0).timestamp() * 1000)
    t2 = int(datetime(2024, 1, 1, 10, 5, 0).timestamp() * 1000)
    t3 = int(datetime(2024, 1, 2, 9, 0, 0).timestamp() * 1000)

    batch = [
        ("orig_1", "t1", "Alice", t1, t1, 0, -1, 1, "Hi there!", "hash1"),
        ("orig_2", "t1", "Alice", t2, t2, 1, -1, 2, "Hey Alice, what's up?", "hash2"),
        ("orig_3", "t1", "Alice", t3, t3, 0, -1, 1, "Good morning on day 2!", "hash3"),
    ]
    db_helper.bulk_insert_messages(batch)

    _, client = app_and_client

    # Before viewing: Alice thread has 2 unread messages
    threads = db_helper.get_threads()
    alice_thread = next(t for t in threads if t["address"] == "Alice")
    assert alice_thread["unread_count"] == 2

    # View conversation
    resp = client.get("/thread/Alice")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    # Check incoming and outgoing bubbles
    assert "message-row--in" in html
    assert "message-row--out" in html
    assert "Hi there!" in html
    # Jinja2/markupsafe may encode ' as &#39; or &#039; depending on version
    assert (
        "Hey Alice, what&#39;s up?" in html
        or "Hey Alice, what&#039;s up?" in html
        or "Hey Alice, what's up?" in html
    )
    assert "Good morning on day 2!" in html

    # Check date separator exists (2 days)
    assert html.count("date-separator") >= 2

    # Verify messages were marked as read
    threads_after = db_helper.get_threads()
    alice_after = next(t for t in threads_after if t["address"] == "Alice")
    assert alice_after["unread_count"] == 0


def test_api_threads_pagination(app_and_client, temp_db):
    db_helper = DatabaseHelper(temp_db)

    # Insert 35 distinct threads
    base_time = int(datetime(2024, 1, 1).timestamp() * 1000)
    batch = []
    for i in range(35):
        addr = f"+1000000{i:02d}"
        t = base_time + (i * 1000)
        batch.append((f"id_{i}", f"t_{i}", addr, t, t, 1, -1, 1, f"Test msg {i}", f"h_{i}"))
    db_helper.bulk_insert_messages(batch)

    _, client = app_and_client

    # Page 1, limit 20
    resp1 = client.get("/api/threads?page=1&limit=20")
    assert resp1.status_code == 200
    d1 = resp1.get_json()
    assert d1["total"] == 35
    assert len(d1["threads"]) == 20
    assert d1["has_more"] is True

    # Page 2, limit 20
    resp2 = client.get("/api/threads?page=2&limit=20")
    assert resp2.status_code == 200
    d2 = resp2.get_json()
    assert len(d2["threads"]) == 15
    assert d2["has_more"] is False


def test_api_messages_pagination(app_and_client, temp_db):
    db_helper = DatabaseHelper(temp_db)

    base_time = int(datetime(2024, 1, 1).timestamp() * 1000)
    batch = []
    for i in range(25):
        t = base_time + (i * 1000)
        batch.append((f"id_{i}", "t1", "Charlie", t, t, 1, -1, 1, f"Message {i}", f"h_{i}"))
    db_helper.bulk_insert_messages(batch)

    _, client = app_and_client

    resp = client.get("/api/messages/Charlie?page=1&limit=10")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["total"] == 25
    assert len(d["messages"]) == 10
    assert d["has_more"] is True
