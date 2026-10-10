"""
Database helper module for SMS Viewer.

Provides a unified DatabaseHelper abstraction for executing database queries,
bulk message insertions, user authentication checks, thread aggregation,
and import logging across all modules.
"""

import sqlite3
from pathlib import Path
from typing import Any, Iterable


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

    def get_threads(self) -> list[dict[str, Any]]:
        """Retrieve thread summaries grouped by address sorted by latest message date."""
        with self.get_connection() as conn:
            cur = conn.execute("""
                SELECT
                    address,
                    MAX(date)  AS latest_date,
                    COUNT(*)   AS message_count,
                    (
                        SELECT body FROM messages m2
                        WHERE m2.address = messages.address
                        ORDER BY m2.date DESC LIMIT 1
                    ) AS last_body
                FROM messages
                GROUP BY address
                ORDER BY latest_date DESC
            """)
            return [dict(row) for row in cur.fetchall()]

    def get_messages_by_address(self, address: str) -> list[dict[str, Any]]:
        """Retrieve all messages for a given sender/address ordered chronologically."""
        with self.get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM messages WHERE address = ? ORDER BY date ASC",
                (address,),
            )
            return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Module-level convenience helper functions
# ---------------------------------------------------------------------------

def get_db_helper(db_path: Path | str) -> DatabaseHelper:
    """Factory helper to obtain a DatabaseHelper instance."""
    return DatabaseHelper(db_path)
