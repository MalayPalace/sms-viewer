"""
FTS5 Search feature module for SMS Viewer.

Provides full-text search over the messages corpus using SQLite FTS5.
Supports plain keywords, prefix (word*), phrase ("exact phrase"),
and column filters (body:OTP, address:HDFC).
"""

import html
import re
from typing import Any


# ---------------------------------------------------------------------------
# Query sanitization helpers
# ---------------------------------------------------------------------------

# Private-use characters that cannot occur in normal SMS text; they mark matches
# so the rest of the body can be HTML-escaped before <mark> tags are inserted.
_HL_START = "\ue000"
_HL_END = "\ue001"

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

    # Remove SQL-dangerous chars: semicolons, single-quotes, null bytes
    query = _UNSAFE.sub("", query)
    # Remove FTS5 structural chars that confuse the parser unless user
    # deliberately typed valid FTS5 syntax (we keep balanced quotes below)
    query = _SPECIAL_FTS.sub("", query)

    # Ensure double-quotes are balanced; strip unpaired trailing quote
    if query.count('"') % 2 != 0:
        query = query.rstrip('"')

    return query.strip()


def _render_snippet(raw: str | None) -> str:
    """Escape the body text, then turn match markers into ``<mark>`` tags."""
    escaped = html.escape(raw or "")
    return escaped.replace(_HL_START, "<mark>").replace(_HL_END, "</mark>")


# ---------------------------------------------------------------------------
# Public search API — sanitizes input then delegates raw DB call to db_helper
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
      (the message text is HTML-escaped first, so the only markup is ``<mark>``).

    Returns an empty list when ``query`` is empty or invalid.
    """
    safe_q = sanitize_fts_query(query)
    if not safe_q:
        return []

    rows = db_helper.fts_search(
        safe_q=safe_q, limit=limit, offset=offset, hl_start=_HL_START, hl_end=_HL_END
    )
    for row in rows:
        row["snippet"] = _render_snippet(row.get("snippet"))
    return rows


def search_messages_count(db_helper: Any, query: str) -> int:
    """Return total number of FTS5 matches for *query* (for pagination).

    Sanitizes the query before passing to db_helper.
    Returns 0 when query is empty or invalid.
    """
    safe_q = sanitize_fts_query(query)
    if not safe_q:
        return 0

    return db_helper.fts_count(safe_q=safe_q)
