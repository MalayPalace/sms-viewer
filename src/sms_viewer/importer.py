"""
ZIP/NDJSON import pipeline for SMS Viewer.

Supports:
- Direct NDJSON file import
- ZIP archive import containing an NDJSON file
- SHA-256 body hash calculation and SQLite UNIQUE constraint deduplication
- Line-by-line streaming processing for low memory usage
- Batch transactions (1,000 records per batch)
- Import log history tracking
"""

import hashlib
import json
import sqlite3
import zipfile
from io import TextIOWrapper
from pathlib import Path
from typing import BinaryIO, Iterable


def _process_line_stream(lines: Iterable[str | bytes], conn: sqlite3.Connection) -> tuple[int, int, int]:
    """Parse lines, execute bulk inserts with deduplication, and return counts.

    Returns:
        tuple[int, int, int]: (records_total, records_imported, records_skipped)
    """
    total = 0
    imported = 0
    batch = []
    batch_size = 1000

    insert_sql = """
        INSERT OR IGNORE INTO messages (
            original_id, thread_id, address, date, date_sent, read, status, type, body, body_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

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
            with conn:
                cur = conn.cursor()
                cur.executemany(insert_sql, batch)
                imported += cur.rowcount if cur.rowcount >= 0 else 0
            batch.clear()

    if batch:
        with conn:
            cur = conn.cursor()
            cur.executemany(insert_sql, batch)
            imported += cur.rowcount if cur.rowcount >= 0 else 0
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
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    total = 0
    imported = 0
    skipped = 0

    try:
        lower_name = filename.lower()
        if lower_name.endswith(".zip"):
            with zipfile.ZipFile(file_source, "r") as zf:
                ndjson_members = [m for m in zf.namelist() if m.lower().endswith(".ndjson")]
                if not ndjson_members:
                    # Fallback: check if there's any file inside if none ends with .ndjson
                    ndjson_members = [m for m in zf.namelist() if not m.endswith("/")]
                if not ndjson_members:
                    raise ValueError("No valid NDJSON files found in the ZIP archive.")

                target_member = ndjson_members[0]
                with zf.open(target_member, "r") as zip_file:
                    text_stream = TextIOWrapper(zip_file, encoding="utf-8", errors="replace")
                    total, imported, skipped = _process_line_stream(text_stream, conn)

        elif lower_name.endswith(".ndjson") or lower_name.endswith(".json"):
            if isinstance(file_source, (str, Path)):
                with open(file_source, "r", encoding="utf-8", errors="replace") as f:
                    total, imported, skipped = _process_line_stream(f, conn)
            else:
                text_stream = TextIOWrapper(file_source, encoding="utf-8", errors="replace")
                total, imported, skipped = _process_line_stream(text_stream, conn)
        else:
            # Fallback attempt to read as stream
            if isinstance(file_source, (str, Path)):
                with open(file_source, "r", encoding="utf-8", errors="replace") as f:
                    total, imported, skipped = _process_line_stream(f, conn)
            else:
                text_stream = TextIOWrapper(file_source, encoding="utf-8", errors="replace")
                total, imported, skipped = _process_line_stream(text_stream, conn)

        # Log import result
        with conn:
            conn.execute(
                """
                INSERT INTO import_log (filename, records_total, records_imported, records_skipped)
                VALUES (?, ?, ?, ?)
                """,
                (filename, total, imported, skipped),
            )

        return {
            "success": True,
            "filename": filename,
            "records_total": total,
            "records_imported": imported,
            "records_skipped": skipped,
        }

    finally:
        conn.close()


def get_import_history(db_path: Path, limit: int = 10) -> list[dict]:
    """Retrieve recent import log records from database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT id, filename, records_total, records_imported, records_skipped, imported_at
            FROM import_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
