"""
FTS5 Search feature module for SMS Viewer.

Provides full-text search over the messages corpus using SQLite FTS5.
Supports plain keywords, prefix (word*), phrase ("exact phrase"),
and column filters (body:OTP, address:HDFC).
"""

import re
import sqlite3
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Query sanitization helpers
# ---------------------------------------------------------------------------

_UNSAFE = re.compile(r"[;'\x00]")
_SPECIAL_FTS = re.compile(r'[()^,]')


def sanitize_fts_query(raw: str) -> str:
    """Sanitize user input for use as an FTS5 MATCH expression.

    Rules:
    - Strip leading/trailing whitespace.
    - Remove characters that could break FTS5 parsing or inject SQL.
    - Preserve ``*`` (prefix), ``"`` only when forming balanced phrase pairs,
      and ``AND``/``OR``/``NOT`` FTS5 operators (case-insensitive).
    - Empty result → return empty string (caller should skip search).
    """
    if not raw:
        return ""

    query = raw.strip()

    # Remove SQL-dangerous chars: semicolons, null bytes
    query = _UNSAFE.sub("", query)
    # Remove FTS5 structural chars that confuse the parser unless user
    # deliberately typed valid FTS5 syntax (we keep balanced quotes below)
    query = _SPECIAL_FTS.sub("", query)

    # Ensure quotes are balanced; strip unpaired trailing quote
    if query.count('"') % 2 != 0:
        query = query.rstrip('"')

    return query.strip()


# ---------------------------------------------------------------------------
# Search engine (stateless functions using DatabaseHelper)
# ---------------------------------------------------------------------------

def search_messages(
    db_helper: Any,
    query: str,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Run a paginated FTS5 MATCH search and return enriched result rows.

    Each result dict contains all ``messages`` columns plus:
    - ``snippet``: HTML snippet with matched terms wrapped in ``<mark>`` tags
      (FTS5 ``highlight()`` function output, safe since it only wraps
      original text without injecting new markup).

    Returns an empty list when ``query`` is empty or invalid.
    """
    safe_q = sanitize_fts_query(query)
    if not safe_q:
        return []

    sql = """
        SELECT
            m.id,
            m.address,
            m.date,
            m.type,
            m.read,
            m.body,
            highlight(messages_fts, 0, '<mark>', '</mark>') AS snippet
        FROM messages_fts
        JOIN messages m ON messages_fts.rowid = m.id
        WHERE messages_fts MATCH ?
        ORDER BY rank
        LIMIT ? OFFSET ?
    """
    try:
        with db_helper.get_connection() as conn:
            cur = conn.execute(sql, (safe_q, limit, offset))
            return [dict(row) for row in cur.fetchall()]
    except sqlite3.OperationalError:
        # Invalid FTS5 query syntax — return empty rather than 500
        return []


def search_messages_count(db_helper: Any, query: str) -> int:
    """Return total number of FTS5 matches for *query* (for pagination)."""
    safe_q = sanitize_fts_query(query)
    if not safe_q:
        return 0

    sql = """
        SELECT COUNT(*) FROM messages_fts
        WHERE messages_fts MATCH ?
    """
    try:
        with db_helper.get_connection() as conn:
            cur = conn.execute(sql, (safe_q,))
            return cur.fetchone()[0]
    except sqlite3.OperationalError:
        return 0
