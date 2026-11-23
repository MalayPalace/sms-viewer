"""
FTS5 Search feature module for SMS Viewer.

Provides full-text search over the messages corpus using SQLite FTS5.
Supports plain keywords, prefix (word*), phrase ("exact phrase"),
column filters (body:OTP, address:HDFC) and date filters
(date:2024-05-20, date:2024-05, date:2024, date:2024-05-01..2024-05-31).
"""

import calendar
import html
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Query sanitization helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Date filter:  date:2024 | date:2024-05 | date:2024-05-20 | date:2024-05-01..2024-05-31
# ---------------------------------------------------------------------------

_DATE_TOKEN = re.compile(r"\bdate:(\S*)", re.IGNORECASE)
_DATE_PART = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")


@dataclass
class ParsedQuery:
    """A raw search string split into its FTS text and date bounds (epoch ms)."""

    text: str = ""
    start_ms: int | None = None
    end_ms: int | None = None
    error: str | None = None

    def get_text(self) -> str:
        return self.text

    def get_start_ms(self) -> int | None:
        return self.start_ms

    def get_end_ms(self) -> int | None:
        return self.end_ms

    def get_error(self) -> str | None:
        return self.error

    def has_date(self) -> bool:
        return self.start_ms is not None or self.end_ms is not None


def _bound_ms(part: str, end: bool) -> int:
    """Epoch ms of the first (or last) instant of a YYYY / YYYY-MM / YYYY-MM-DD period."""
    match = _DATE_PART.match(part)
    if not match:
        raise ValueError(f"Invalid date '{part}'. Use YYYY, YYYY-MM or YYYY-MM-DD.")
    year, month, day = int(match.group(1)), match.group(2), match.group(3)
    try:
        if day:
            first = datetime(year, int(month), int(day))
            last = datetime(year, int(month), int(day), 23, 59, 59, 999000)
        elif month:
            days = calendar.monthrange(year, int(month))[1]
            first = datetime(year, int(month), 1)
            last = datetime(year, int(month), days, 23, 59, 59, 999000)
        else:
            first = datetime(year, 1, 1)
            last = datetime(year, 12, 31, 23, 59, 59, 999000)
    except ValueError:
        raise ValueError(f"Invalid date '{part}'.") from None
    return int((last if end else first).timestamp() * 1000)


def parse_date_filter(value: str) -> tuple[int | None, int | None]:
    """Convert a ``date:`` value into inclusive epoch-ms bounds (either may be None)."""
    if ".." in value:
        left, right = value.split("..", 1)
        start = _bound_ms(left, end=False) if left else None
        end = _bound_ms(right, end=True) if right else None
        if start is None and end is None:
            raise ValueError("Empty date range.")
        if start is not None and end is not None and start > end:
            raise ValueError("Date range start is after its end.")
        return start, end
    return _bound_ms(value, end=False), _bound_ms(value, end=True)


def parse_search_query(raw: str | None) -> ParsedQuery:
    """Split ``date:`` filters out of *raw*; the remainder is the FTS text."""
    raw = raw or ""
    match = _DATE_TOKEN.search(raw)
    text = _DATE_TOKEN.sub(" ", raw)
    if not match:
        return ParsedQuery(text=text)
    try:
        start, end = parse_date_filter(match.group(1))
    except ValueError as err:
        return ParsedQuery(text=text, error=str(err))
    return ParsedQuery(text=text, start_ms=start, end_ms=end)


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
    parsed = parse_search_query(query)
    safe_q = sanitize_fts_query(parsed.get_text())
    if parsed.get_error() or not (safe_q or parsed.has_date()):
        return []

    rows = db_helper.fts_search(
        safe_q=safe_q,
        limit=limit,
        offset=offset,
        hl_start=_HL_START,
        hl_end=_HL_END,
        start_ms=parsed.get_start_ms(),
        end_ms=parsed.get_end_ms(),
    )
    for row in rows:
        row["snippet"] = _render_snippet(row.get("snippet"))
    return rows


def search_messages_count(db_helper: Any, query: str) -> int:
    """Return total number of FTS5 matches for *query* (for pagination).

    Sanitizes the query before passing to db_helper.
    Returns 0 when query is empty or invalid.
    """
    parsed = parse_search_query(query)
    safe_q = sanitize_fts_query(parsed.get_text())
    if parsed.get_error() or not (safe_q or parsed.has_date()):
        return 0

    return db_helper.fts_count(
        safe_q=safe_q, start_ms=parsed.get_start_ms(), end_ms=parsed.get_end_ms()
    )
