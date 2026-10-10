"""
Database module for SMS Viewer.

Handles:
- Database path resolution (CLI arg → env var → default ~/.sms-viewer/sms.db)
- Connection management per Flask request (via Flask's `g`)
- Schema initialization (tables, indexes, FTS5 virtual table, sync triggers)
- Schema migrations (versioned, idempotent)
"""

import os
import sqlite3
from pathlib import Path

from flask import g

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_DATA_DIR = Path.home() / ".sms-viewer"
DEFAULT_DB_NAME = "sms.db"

# Increment this when the schema changes. Migration logic below must handle
# upgrading from any prior version to this one.
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def resolve_db_path(custom_path: str | None = None) -> Path:
    """Resolve the SQLite database file path.

    Priority order:
      1. ``custom_path`` argument (from ``--db-path`` CLI flag)
      2. ``SMS_VIEWER_DB`` environment variable
      3. Default: ``~/.sms-viewer/sms.db``

    The parent directory is created automatically if it does not exist.
    """
    if custom_path:
        db_path = Path(custom_path).expanduser().resolve()
    elif os.environ.get("SMS_VIEWER_DB"):
        db_path = Path(os.environ["SMS_VIEWER_DB"]).expanduser().resolve()
    else:
        db_path = DEFAULT_DATA_DIR / DEFAULT_DB_NAME

    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def get_db(db_path: Path) -> sqlite3.Connection:
    """Open (or reuse) a per-request database connection.

    The connection is stored in Flask's application context ``g`` so that
    the same connection is reused for the duration of a single request and
    automatically closed at teardown via ``close_db``.
    """
    if "db" not in g:
        g.db = sqlite3.connect(
            db_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrent read performance
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def close_db(e=None) -> None:  # noqa: ARG001
    """Close the per-request database connection (registered as teardown)."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------------------------------------------------------------------------
# Schema initialisation & migration
# ---------------------------------------------------------------------------

_DDL_MESSAGES = """
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    original_id     TEXT,
    thread_id       TEXT,
    address         TEXT    NOT NULL,
    date            INTEGER NOT NULL,
    date_sent       INTEGER,
    read            INTEGER DEFAULT 1,
    status          INTEGER DEFAULT -1,
    type            INTEGER DEFAULT 1,
    body            TEXT    NOT NULL,
    body_hash       TEXT    NOT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, address, body_hash)
);
"""

_DDL_MESSAGES_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_messages_address      ON messages(address);",
    "CREATE INDEX IF NOT EXISTS idx_messages_date         ON messages(date);",
    "CREATE INDEX IF NOT EXISTS idx_messages_address_date ON messages(address, date DESC);",
]

_DDL_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    body,
    address,
    content='messages',
    content_rowid='id',
    tokenize='unicode61'
);
"""

_DDL_FTS_TRIGGERS = [
    # After INSERT — add to FTS index
    """
    CREATE TRIGGER IF NOT EXISTS messages_ai
    AFTER INSERT ON messages BEGIN
        INSERT INTO messages_fts(rowid, body, address)
        VALUES (new.id, new.body, new.address);
    END;
    """,
    # After DELETE — remove from FTS index
    """
    CREATE TRIGGER IF NOT EXISTS messages_ad
    AFTER DELETE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, body, address)
        VALUES('delete', old.id, old.body, old.address);
    END;
    """,
    # After UPDATE — update FTS index
    """
    CREATE TRIGGER IF NOT EXISTS messages_au
    AFTER UPDATE ON messages BEGIN
        INSERT INTO messages_fts(messages_fts, rowid, body, address)
        VALUES('delete', old.id, old.body, old.address);
        INSERT INTO messages_fts(rowid, body, address)
        VALUES (new.id, new.body, new.address);
    END;
    """,
]

_DDL_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    UNIQUE NOT NULL,
    password_hash TEXT    NOT NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

_DDL_IMPORT_LOG = """
CREATE TABLE IF NOT EXISTS import_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    filename         TEXT    NOT NULL,
    records_total    INTEGER DEFAULT 0,
    records_imported INTEGER DEFAULT 0,
    records_skipped  INTEGER DEFAULT 0,
    imported_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

_DDL_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""


def init_db(db_path: Path) -> None:
    """Create all tables, indexes, FTS virtual table, and triggers.

    This function is idempotent — safe to call on every application startup.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            # Core tables
            conn.execute(_DDL_MESSAGES)
            for stmt in _DDL_MESSAGES_INDEXES:
                conn.execute(stmt)

            conn.execute(_DDL_FTS)
            for stmt in _DDL_FTS_TRIGGERS:
                conn.execute(stmt)

            conn.execute(_DDL_USERS)
            conn.execute(_DDL_IMPORT_LOG)
            conn.execute(_DDL_SCHEMA_VERSION)

            # Stamp version if not yet set
            cur = conn.execute("SELECT version FROM schema_version LIMIT 1")
            if cur.fetchone() is None:
                conn.execute(
                    "INSERT INTO schema_version(version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )

        _migrate(conn)
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply any pending schema migrations.

    Each migration is guarded by a version check and is idempotent.
    Add new ``elif version == N:`` blocks here as the schema evolves.
    """
    cur = conn.execute("SELECT version FROM schema_version LIMIT 1")
    row = cur.fetchone()
    if row is None:
        return
    version = row[0]

    # Example: if version == 1: apply migration to version 2, bump version
    #TODO: (No migrations needed yet — schema is at v1.)
    _ = version  # suppress unused-variable warning


def has_any_user(db_path: Path) -> bool:
    """Return True if at least one user account exists in the database."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM users")
        return cur.fetchone()[0] > 0
    finally:
        conn.close()
