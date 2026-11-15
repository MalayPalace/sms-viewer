"""
Unit and integration tests for DatabaseHelper, Importer, and Import API.
"""

import json
import sqlite3
import zipfile
from pathlib import Path
import pytest

from sms_viewer.app import create_app
from sms_viewer.database.db import init_db
from sms_viewer.database.db_helper import DatabaseHelper
from sms_viewer.feature.importer import get_import_history, import_backup_file


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_sms.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def sample_ndjson(tmp_path):
    data = [
        {
            "_id": "1",
            "thread_id": "101",
            "address": "+1234567890",
            "date": 1600000000000,
            "date_sent": 1600000000000,
            "read": 1,
            "status": -1,
            "type": 1,
            "body": "Hello World! Your OTP is 123456"
        },
        {
            "_id": "2",
            "thread_id": "101",
            "address": "+1234567890",
            "date": 1600000005000,
            "date_sent": 1600000005000,
            "read": 1,
            "status": -1,
            "type": 2,
            "body": "Thanks, logged in."
        },
        {
            "_id": "3",
            "thread_id": "102",
            "address": "HDFCBK",
            "date": 1600000010000,
            "date_sent": 1600000010000,
            "read": 1,
            "status": -1,
            "type": 1,
            "body": "INR 500.00 debited from A/C XX1234 on 12-SEP-26."
        }
    ]
    file_path = tmp_path / "sample_backup.ndjson"
    with open(file_path, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item) + "\n")
    return file_path


@pytest.fixture
def sample_zip(tmp_path, sample_ndjson):
    zip_path = tmp_path / "sample_backup.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(sample_ndjson, arcname="messages.ndjson")
    return zip_path


def test_db_helper_operations(temp_db):
    db_helper = DatabaseHelper(temp_db)
    assert db_helper.has_any_user() is False

    uid = db_helper.create_user("admin", "hashed_pass")
    assert uid > 0
    assert db_helper.has_any_user() is True

    user = db_helper.get_user_by_username("admin")
    assert user is not None
    assert user["username"] == "admin"


def test_import_ndjson(temp_db, sample_ndjson):
    res = import_backup_file(sample_ndjson, sample_ndjson.name, temp_db)
    assert res["success"] is True
    assert res["records_total"] == 3
    assert res["records_imported"] == 3
    assert res["records_skipped"] == 0

    # Verify rows via DatabaseHelper
    db_helper = DatabaseHelper(temp_db)
    threads = db_helper.get_threads()
    assert len(threads) == 2  # 2 addresses: +1234567890 and HDFCBK


def test_import_deduplication(temp_db, sample_ndjson):
    # First import
    res1 = import_backup_file(sample_ndjson, sample_ndjson.name, temp_db)
    assert res1["records_imported"] == 3

    # Second import (exact same file)
    res2 = import_backup_file(sample_ndjson, sample_ndjson.name, temp_db)
    assert res2["records_total"] == 3
    assert res2["records_imported"] == 0
    assert res2["records_skipped"] == 3

    # History tracking check
    history = get_import_history(temp_db)
    assert len(history) == 2
    assert history[0]["records_skipped"] == 3


def test_import_zip(temp_db, sample_zip):
    res = import_backup_file(sample_zip, sample_zip.name, temp_db)
    assert res["success"] is True
    assert res["records_total"] == 3
    assert res["records_imported"] == 3

    db_helper = DatabaseHelper(temp_db)
    messages = db_helper.get_messages_by_address("HDFCBK")
    assert len(messages) == 1
    assert "INR 500.00 debited" in messages[0]["body"]


def test_api_import_endpoint(temp_db, sample_zip):
    app = create_app(db_path=temp_db, secret_key="test_secret")
    app.config["TESTING"] = True
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["username"] = "testuser"
        sess["csrf_token"] = "tok"

    with open(sample_zip, "rb") as f:
        response = client.post(
            "/api/import",
            headers={"X-CSRFToken": "tok"},
            data={"file": (f, "backup.zip")},
            content_type="multipart/form-data",
        )

    assert response.status_code == 200
    json_data = response.get_json()
    assert json_data["success"] is True
    assert json_data["records_imported"] == 3

    # Test history endpoint
    hist_resp = client.get("/api/import/history")
    assert hist_resp.status_code == 200
    hist_json = hist_resp.get_json()
    assert len(hist_json["history"]) == 1
    assert hist_json["history"][0]["filename"] == "backup.zip"
