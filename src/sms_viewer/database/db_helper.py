"""
Database helper module for SMS Viewer.

Provides a unified DatabaseHelper abstraction for executing database queries,
bulk message insertions, user authentication checks, thread aggregation,
and import logging across all modules.
"""

import sqlite3
from pathlib import Path
from typing import Any


class DatabaseHelper:
    """Central database helper class for executing SQLite queries and transactions."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).expanduser().resolve()

    def get_connection(self) -> sqlite3.Connection:
        """Create and configure a new SQLite connection."""
        conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # -----------------------------------------------------------------------
    # User / Auth operations
    # -----------------------------------------------------------------------

    def has_any_user(self) -> bool:
        """Return True if at least one user account exists."""
        with self.get_connection() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM users")
            return cur.fetchone()[0] > 0

    def create_user(self, username: str, password_hash: str) -> int:
        """Create a new user account and return inserted user ID."""
        with self.get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
            conn.commit()
            return cur.lastrowid

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        """Fetch user record by username."""
        with self.get_connection() as conn:
            cur = conn.execute(
                "SELECT id, username, password_hash, created_at FROM users WHERE username = ?",
                (username,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    # -----------------------------------------------------------------------
    # Message / Import operations
    # -----------------------------------------------------------------------

    def bulk_insert_messages(self, batch: list[tuple]) -> int:
        """Execute bulk insertion of messages using INSERT OR IGNORE.

        Args:
            batch: List of tuples representing message attributes.

        Returns:
            int: Number of new rows actually inserted.
        """
        insert_sql = """
            INSERT OR IGNORE INTO messages (
                original_id, thread_id, address, date, date_sent, read, status, type, body, body_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.executemany(insert_sql, batch)
            conn.commit()
            return cur.rowcount if cur.rowcount >= 0 else 0

    def log_import(self, filename: str, records_total: int, records_imported: int, records_skipped: int) -> int:
        """Log an import run into import_log table."""
        with self.get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO import_log (filename, records_total, records_imported, records_skipped)
                VALUES (?, ?, ?, ?)
                """,
                (filename, records_total, records_imported, records_skipped),
            )
            conn.commit()
            return cur.lastrowid

    def get_import_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Retrieve recent import log records."""
        with self.get_connection() as conn:
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

    # -----------------------------------------------------------------------
    # Views / Query operations
    # -----------------------------------------------------------------------

    def get_threads(self, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        """Retrieve thread summaries grouped by address sorted by latest message date.

        Supports optional pagination via limit and offset.
        """
        query = """
            SELECT
                address,
                MAX(date)  AS latest_date,
                COUNT(*)   AS message_count,
                SUM(CASE WHEN read = 0 THEN 1 ELSE 0 END) AS unread_count,
                (
                    SELECT body FROM messages m2
                    WHERE m2.address = messages.address
                    ORDER BY m2.date DESC LIMIT 1
                ) AS last_body,
                (
                    SELECT type FROM messages m2
                    WHERE m2.address = messages.address
                    ORDER BY m2.date DESC LIMIT 1
                ) AS last_type
            FROM messages
            GROUP BY address
            ORDER BY latest_date DESC
        """
        params: list[Any] = []
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        with self.get_connection() as conn:
            cur = conn.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def get_threads_count(self) -> int:
        """Return total number of unique conversation threads."""
        with self.get_connection() as conn:
            cur = conn.execute("SELECT COUNT(DISTINCT address) FROM messages")
            return cur.fetchone()[0]

    def get_messages_by_address(
        self, address: str, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Retrieve all messages for a given sender/address ordered chronologically."""
        query = "SELECT * FROM messages WHERE address = ? ORDER BY date ASC"
        params: list[Any] = [address]
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        with self.get_connection() as conn:
            cur = conn.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def get_messages_count_by_address(self, address: str) -> int:
        """Return total number of messages for a given address."""
        with self.get_connection() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE address = ?", [address]
            )
            return cur.fetchone()[0]

    def mark_thread_read(self, address: str) -> int:
        """Mark unread messages in a thread as read. Returns number of updated messages."""
        with self.get_connection() as conn:
            cur = conn.execute(
                "UPDATE messages SET read = 1 WHERE address = ? AND read = 0", [address]
            )
            conn.commit()
            return cur.rowcount if cur.rowcount >= 0 else 0

    # -----------------------------------------------------------------------
    # FTS5 Search operations
    # -----------------------------------------------------------------------

    def search_messages(
            self, query: str, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Full-text search over messages using SQLite FTS5.

        Delegates to :func:`sms_viewer.feature.search.search_messages`.
        Returns enriched rows with a ``snippet`` field containing HTML
        ``<mark>`` highlights around matched terms.
        """
        from sms_viewer.feature.search import search_messages as _search
        return _search(self, query=query, limit=limit, offset=offset)

    def search_messages_count(self, query: str) -> int:
        """Return total FTS5 match count for *query* (used for pagination)."""
        from sms_viewer.feature.search import search_messages_count as _count
        return _count(self, query=query)


# ---------------------------------------------------------------------------
# Module-level convenience helper functions
# ---------------------------------------------------------------------------

def get_db_helper(db_path: Path | str) -> DatabaseHelper:
    """Factory helper to obtain a DatabaseHelper instance."""
    return DatabaseHelper(db_path)
