"""
ZIP/NDJSON import pipeline for SMS Viewer.

Supports:
- Direct NDJSON file import
- ZIP archive import containing an NDJSON file
- SHA-256 body hash calculation and SQLite UNIQUE constraint deduplication
- Line-by-line streaming processing for low memory usage
- Batch transactions (1,000 records per batch) via DatabaseHelper
- Import log history tracking via DatabaseHelper
"""

import hashlib
import json
import zipfile
from io import TextIOWrapper
from pathlib import Path
from typing import BinaryIO, Iterable

from sms_viewer.database.db_helper import DatabaseHelper


def _process_line_stream(lines: Iterable[str | bytes], db_helper: DatabaseHelper) -> tuple[int, int, int]:
    """Parse lines, execute bulk inserts via DatabaseHelper, and return counts.

    Returns:
        tuple[int, int, int]: (records_total, records_imported, records_skipped)
    """
    total = 0
    imported = 0
    batch = []
    batch_size = 1000

    for line in lines:
        if isinstance(line, bytes):
            line_str = line.decode("utf-8", errors="replace").strip()
        else:
            line_str = line.strip()

        if not line_str:
            continue

        total += 1
        try:
            item = json.loads(line_str)
        except json.JSONDecodeError:
            continue

        body = str(item.get("body", ""))
        address = str(item.get("address") or item.get("contact") or "Unknown")
        date_val = item.get("date")

        if date_val is None:
            continue

        try:
            date_int = int(date_val)
        except (ValueError, TypeError):
            continue

        date_sent = item.get("date_sent")
        date_sent_int = int(date_sent) if date_sent is not None and str(date_sent).isdigit() else None
        read_int = int(item.get("read", 1))
        status_int = int(item.get("status", -1))
        msg_type_int = int(item.get("type", 1))
        original_id = str(item.get("_id")) if item.get("_id") is not None else None
        thread_id = str(item.get("thread_id")) if item.get("thread_id") is not None else None

        body_hash = hashlib.sha256(body.strip().encode("utf-8")).hexdigest()

        batch.append((
            original_id,
            thread_id,
            address,
            date_int,
            date_sent_int,
            read_int,
            status_int,
            msg_type_int,
            body,
            body_hash,
        ))

        if len(batch) >= batch_size:
            imported += db_helper.bulk_insert_messages(batch)
            batch.clear()

    if batch:
        imported += db_helper.bulk_insert_messages(batch)
        batch.clear()

    skipped = total - imported
    return total, imported, skipped


def import_backup_file(file_source: str | Path | BinaryIO, filename: str, db_path: Path) -> dict:
    """Import SMS data from an NDJSON file or ZIP archive into the SQLite database.

    Args:
        file_source: Path to file or binary file-like object stream.
        filename: Name of the uploaded file (used to infer extension and for logging).
        db_path: Path to the SQLite database file.

    Returns:
        dict: Import status and metrics summary.
    """
    db_helper = DatabaseHelper(db_path)
    lower_name = filename.lower()
    total, imported, skipped = 0, 0, 0

    if lower_name.endswith(".zip"):
        with zipfile.ZipFile(file_source, "r") as zf:
            ndjson_members = [m for m in zf.namelist() if m.lower().endswith(".ndjson")]
            if not ndjson_members:
                ndjson_members = [m for m in zf.namelist() if not m.endswith("/")]
            if not ndjson_members:
                raise ValueError("No valid NDJSON files found in the ZIP archive.")

            target_member = ndjson_members[0]
            with zf.open(target_member, "r") as zip_file:
                text_stream = TextIOWrapper(zip_file, encoding="utf-8", errors="replace")
                total, imported, skipped = _process_line_stream(text_stream, db_helper)

    elif lower_name.endswith(".ndjson") or lower_name.endswith(".json"):
        if isinstance(file_source, (str, Path)):
            with open(file_source, "r", encoding="utf-8", errors="replace") as f:
                total, imported, skipped = _process_line_stream(f, db_helper)
        else:
            text_stream = TextIOWrapper(file_source, encoding="utf-8", errors="replace")
            total, imported, skipped = _process_line_stream(text_stream, db_helper)
    else:
        if isinstance(file_source, (str, Path)):
            with open(file_source, "r", encoding="utf-8", errors="replace") as f:
                total, imported, skipped = _process_line_stream(f, db_helper)
        else:
            text_stream = TextIOWrapper(file_source, encoding="utf-8", errors="replace")
            total, imported, skipped = _process_line_stream(text_stream, db_helper)

    # Log import run
    db_helper.log_import(filename, total, imported, skipped)

    return {
        "success": True,
        "filename": filename,
        "records_total": total,
        "records_imported": imported,
        "records_skipped": skipped,
    }


def get_import_history(db_path: Path, limit: int = 10) -> list[dict]:
    """Retrieve recent import log records using DatabaseHelper."""
    db_helper = DatabaseHelper(db_path)
    return db_helper.get_import_history(limit=limit)
