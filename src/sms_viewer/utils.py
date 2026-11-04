"""
Utility helpers and template filters for SMS Viewer.

Provides date/time formatting, avatar color hashing, and message grouping.
"""

from datetime import datetime, timezone
from typing import Any


def epoch_to_datetime(epoch_ms: int | float | None) -> datetime | None:
    """Convert epoch milliseconds to a datetime object in local time."""
    if epoch_ms is None:
        return None
    try:
        ts = float(epoch_ms) / 1000.0
        return datetime.fromtimestamp(ts)
    except (ValueError, OSError, OverflowError):
        return None


def format_timestamp(epoch_ms: int | float | None) -> str:
    """Format epoch milliseconds into a concise thread timestamp.

    - Today: '10:30 AM'
    - Yesterday: 'Yesterday'
    - Within this year: 'Sep 12'
    - Older: 'Sep 12, 2024'
    """
    dt = epoch_to_datetime(epoch_ms)
    if not dt:
        return ""

    now = datetime.now()
    today = now.date()
    msg_date = dt.date()

    delta_days = (today - msg_date).days

    if delta_days == 0:
        return dt.strftime("%I:%M %p").lstrip("0")
    if delta_days == 1:
        return "Yesterday"
    if msg_date.year == today.year:
        return dt.strftime("%b %d")
    return dt.strftime("%b %d, %Y")


def format_time(epoch_ms: int | float | None) -> str:
    """Format epoch milliseconds to time string for message bubbles (e.g. '10:30 AM')."""
    dt = epoch_to_datetime(epoch_ms)
    if not dt:
        return ""
    return dt.strftime("%I:%M %p").lstrip("0")


def format_date_label(epoch_ms: int | float | None) -> str:
    """Format epoch milliseconds for date separator labels (e.g. 'Saturday, Sep 12')."""
    dt = epoch_to_datetime(epoch_ms)
    if not dt:
        return ""

    today = datetime.now().date()
    msg_date = dt.date()
    delta_days = (today - msg_date).days

    if delta_days == 0:
        return "Today"
    if delta_days == 1:
        return "Yesterday"
    if msg_date.year == today.year:
        return dt.strftime("%A, %b %d")
    return dt.strftime("%A, %b %d, %Y")


def avatar_color_index(address: str | None) -> int:
    """Generate consistent 0-7 index for avatar color palette based on address."""
    if not address:
        return 0
    return sum(ord(c) for c in str(address)) % 8


def avatar_initial(address: str | None) -> str:
    """Extract clean single initial for thread avatar."""
    if not address:
        return "#"
    clean = str(address).strip().lstrip("+")
    return clean[0].upper() if clean else "#"


def group_messages_by_date(messages: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Group chronological messages by calendar day for date separator display.

    Returns:
        List of tuples: [(date_label, [message, ...]), ...]
    """
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    current_key = None
    current_list: list[dict[str, Any]] = []

    for msg in messages:
        dt = epoch_to_datetime(msg.get("date"))
        key = dt.strftime("%Y-%m-%d") if dt else "Unknown"
        label = format_date_label(msg.get("date")) if dt else "Unknown"

        if key != current_key:
            if current_list:
                groups.append((current_label, current_list))
            current_key = key
            current_label = label
            current_list = [msg]
        else:
            current_list.append(msg)

    if current_list:
        groups.append((current_label, current_list))

    return groups
