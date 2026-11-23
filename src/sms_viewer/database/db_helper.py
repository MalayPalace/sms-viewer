"""
Database helper module for SMS Viewer.

Provides a unified DatabaseHelper abstraction for executing database queries,
bulk message insertions, user authentication checks, thread aggregation,
and import logging across all modules.
"""

import sqlite3
from pathlib import Path
from typing import Any

EXPORT_FIELDS = (
    "id", "original_id", "thread_id", "address", "date", "date_sent",
    "read", "status", "type", "body",
)

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

    def count_messages_where(self, where: str = "", params: list[Any] | None = None) -> int:
        """Count messages matching a pre-built WHERE clause (e.g. ``" WHERE date >= ?"``)."""
        with self.get_connection() as conn:
            cur = conn.execute(f"SELECT COUNT(*) FROM messages{where}", params or [])
            return cur.fetchone()[0]

    def get_messages_where(
        self, where: str = "", params: list[Any] | None = None
    ) -> list[sqlite3.Row]:
        """Fetch export columns of messages matching a pre-built WHERE clause, oldest first."""
        cols = ", ".join(EXPORT_FIELDS)
        query = f"SELECT {cols} FROM messages{where} ORDER BY date ASC, id ASC"
        with self.get_connection() as conn:
            return conn.execute(query, params or []).fetchall()

    def mark_thread_read(self, address: str) -> int:
        """Mark unread messages in a thread as read. Returns number of updated messages."""
        with self.get_connection() as conn:
            cur = conn.execute(
                "UPDATE messages SET read = 1 WHERE address = ? AND read = 0", [address]
            )
            conn.commit()
            return cur.rowcount if cur.rowcount >= 0 else 0

    # -----------------------------------------------------------------------
    # FTS5 Search operations — raw DB query methods
    # (called by feature/search.py after input sanitization)
    # -----------------------------------------------------------------------

    @staticmethod
    def _date_clause(start_ms: int | None, end_ms: int | None) -> tuple[str, list[int]]:
        clauses, params = [], []
        if start_ms is not None:
            clauses.append("m.date >= ?")
            params.append(start_ms)
        if end_ms is not None:
            clauses.append("m.date <= ?")
            params.append(end_ms)
        date_clause = "".join(f" AND {c}" for c in clauses)
        return date_clause, params

    def fts_search(
        self,
        safe_q: str,
        limit: int = 20,
        offset: int = 0,
        hl_start: str = "<mark>",
        hl_end: str = "</mark>",
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search messages by FTS5 expression and/or date range; return raw rows.

        Each row contains the message columns plus a ``snippet`` field. With an FTS
        expression the snippet wraps matches in ``hl_start``/``hl_end`` (FTS5
        ``highlight()``); with only a date range it is the plain body. Text is
        returned unescaped; callers must escape it.

        Args:
            safe_q:   Pre-sanitized FTS5 MATCH expression (may be empty for date-only).
            start_ms: Inclusive lower bound on message date (epoch ms).
            end_ms:   Inclusive upper bound on message date (epoch ms).
        """
        date_sql, date_params = self._date_clause(start_ms, end_ms)
        if safe_q:
            sql = f"""
                SELECT m.id, m.address, m.date, m.type, m.read, m.body,
                       highlight(messages_fts, 0, ?, ?) AS snippet
                FROM messages_fts AS fts
                JOIN messages AS m ON fts.rowid = m.id
                WHERE messages_fts MATCH ?{date_sql}
                ORDER BY rank
                LIMIT ? OFFSET ?
            """
            params = [hl_start, hl_end, safe_q, *date_params, limit, offset]
        else:
            sql = f"""
                SELECT m.id, m.address, m.date, m.type, m.read, m.body, m.body AS snippet
                FROM messages AS m
                WHERE 1=1{date_sql}
                ORDER BY m.date DESC, m.id DESC
                LIMIT ? OFFSET ?
            """
            params = [*date_params, limit, offset]
        try:
            with self.get_connection() as conn:
                cur = conn.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
        except sqlite3.OperationalError:
            # Invalid FTS5 query syntax — return empty rather than 500
            return []

    def fts_count(
        self, safe_q: str, start_ms: int | None = None, end_ms: int | None = None
    ) -> int:
        """Return total matches for the same filters as ``fts_search``."""
        date_sql, date_params = self._date_clause(start_ms, end_ms)
        if safe_q:
            sql = f"""
                SELECT COUNT(*)
                FROM messages_fts AS fts
                JOIN messages AS m ON fts.rowid = m.id
                WHERE messages_fts MATCH ?{date_sql}
            """
            params = [safe_q, *date_params]
        else:
            sql = f"SELECT COUNT(*) FROM messages AS m WHERE 1=1{date_sql}"
            params = date_params
        try:
            with self.get_connection() as conn:
                cur = conn.execute(sql, params)
                return cur.fetchone()[0]
        except sqlite3.OperationalError:
            return 0


# ---------------------------------------------------------------------------
# Module-level convenience helper functions
# ---------------------------------------------------------------------------

def get_db_helper(db_path: Path | str) -> DatabaseHelper:
    """Factory helper to obtain a DatabaseHelper instance."""
    return DatabaseHelper(db_path)
