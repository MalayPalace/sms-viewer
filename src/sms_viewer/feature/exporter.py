"""
Export feature module for SMS Viewer.

Exports messages within an (inclusive) date range as a JSON document whose
structure mirrors the ``messages`` table columns.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any


def parse_date_range(from_date: str | None, to_date: str | None) -> tuple[int | None, int | None]:
    """Convert ISO ``YYYY-MM-DD`` strings to epoch-millisecond bounds.

    ``from_date`` maps to the start of that local day and ``to_date`` to the
    last millisecond of that local day. Empty/None values mean unbounded.
    Raises ``ValueError`` for malformed dates or when from > to.
    """
    start_ms = end_ms = None
    start_day = end_day = None
    if from_date:
        start_day = date.fromisoformat(from_date.strip())
        start_ms = int(datetime.combine(start_day, time.min).timestamp() * 1000)
    if to_date:
        end_day = date.fromisoformat(to_date.strip())
        next_day = datetime.combine(end_day + timedelta(days=1), time.min)
        end_ms = int(next_day.timestamp() * 1000) - 1
    if start_day and end_day and start_day > end_day:
        raise ValueError("'from' date must not be after 'to' date.")
    return start_ms, end_ms


def count_messages(db_helper: Any, start_ms: int | None, end_ms: int | None) -> int:
    """Count messages within the epoch-ms range."""
    where, params = _where(start_ms, end_ms)
    return db_helper.count_messages_where(where, params)


def export_messages(db_helper: Any, start_ms: int | None, end_ms: int | None) -> dict[str, Any]:
    """Build the export document for the given epoch-ms range."""
    where, params = _where(start_ms, end_ms)
    query_result = db_helper.get_messages_where(where, params)

    rows: list[dict[str, Any]] = []
    for row in query_result:
        rows.append(dict(row))

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "from": start_ms,
        "to": end_ms,
        "count": len(rows),
        "messages": rows,
    }


def export_to_json(db_helper: Any, start_ms: int | None, end_ms: int | None) -> str:
    """Return the export document serialised as pretty JSON."""
    return json.dumps(export_messages(db_helper, start_ms, end_ms), ensure_ascii=False, indent=2)


def _where(start_ms: int | None, end_ms: int | None) -> tuple[str, list[int]]:
    clauses, params = [], []
    if start_ms is not None:
        clauses.append("date >= ?")
        params.append(start_ms)
    if end_ms is not None:
        clauses.append("date <= ?")
        params.append(end_ms)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params
