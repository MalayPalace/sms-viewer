"""
Entity Recognition module for SMS Viewer.

Provides a Jinja2-safe filter ``highlight_entities`` that scans message
body text for URLs, email addresses, phone numbers, and OTP codes, then
wraps each match in a clickable ``<span>`` element styled as an entity badge.
"""

import re
from markupsafe import Markup, escape


# ---------------------------------------------------------------------------
# Regex patterns (compiled once at import time)
# ---------------------------------------------------------------------------

# URLs: http / https links (greedy up to whitespace or common delimiters)
_RE_URL = re.compile(
    r'https?://'
    r'[^\s<>"{}|\\^\[\]`\'()]*'
    r'[^\s<>"{}|\\^\[\]`\'().,;:!?]',
    re.IGNORECASE,
)

# Email addresses
_RE_EMAIL = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
)

# OTP with preceding keyword (highest priority — matched before standalone)
# e.g. "OTP: 4821", "code is 123456", "PIN 9900"
_RE_OTP_KEYWORD = re.compile(
    r'(?:'
    r'(?:one[- ]time[- ](?:password|pass|code))'
    r'|(?:otp)'
    r'|(?:passcode)'
    r'|(?:password)'
    r'|(?:p/?w)'
    r'|(?:pin)'
    r'|(?:code)'
    r'|(?:token)'
    r'|(?:verification[- ]code)'
    r'|(?:auth(?:entication)?[- ]code)'
    r')'
    r'[\s:is#\-]*'
    r'(\d{4,8})',
    re.IGNORECASE,
)

# Standalone 4–8 digit number (lower priority — only used when no keyword OTP)
_RE_OTP_STANDALONE = re.compile(r'\b(\d{4,8})\b')

# Phone numbers: international and local formats with ≥7 digits
# Matches patterns like +91-98765-43210, (022) 6789-0123, 1800 123 4567
_RE_PHONE = re.compile(
    r'(?<!\d)'                          # not preceded by digit
    r'(?:\+?\d{1,3}[\s.\-]?)?'         # optional country code
    r'(?:\(?\d{1,4}\)?[\s.\-]?)?'      # optional area code
    r'\d{3,5}'                          # main block
    r'[\s.\-]?\d{3,5}'                 # second block
    r'(?:[\s.\-]?\d{1,5})?'            # optional trailing block
    r'(?!\d)',                          # not followed by digit
    re.ASCII,
)

_PHONE_MIN_DIGITS = 7  # require at least this many digits to be a phone number


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _digit_count(s: str) -> int:
    return sum(1 for c in s if c.isdigit())


def _make_span(entity_class: str, text: str, copy_value: str | None = None) -> str:
    """Return an HTML ``<span>`` for an entity badge (as raw string, escaped internally)."""
    safe_text = str(escape(text))
    safe_copy = str(escape(copy_value or text))
    return (
        f'<span class="entity entity--{entity_class}" '
        f'data-copy="{safe_copy}" '
        f'title="Click to copy" '
        f'role="button" tabindex="0" '
        f'aria-label="Copy {entity_class}: {safe_copy}">'
        f'{safe_text}</span>'
    )


# ---------------------------------------------------------------------------
# Core recognizer
# ---------------------------------------------------------------------------

def highlight_entities(text: str | None) -> Markup:
    """Jinja2 filter: scan *text* for entities and return safe HTML Markup.

    Detected entities are wrapped in ``<span class="entity entity--<type>">``
    elements with a ``data-copy`` attribute for clipboard copy on click.

    Entity priority (highest to lowest):
    1. URL
    2. Email
    3. OTP with keyword
    4. Phone number
    5. OTP standalone (only digits not already matched above)
    """
    if not text:
        return Markup("")

    # Collect all matches with their spans and replacement HTML
    # List of (start, end, replacement_html)
    replacements: list[tuple[int, int, str]] = []

    # 1. URLs
    for m in _RE_URL.finditer(text):
        replacements.append((m.start(), m.end(), _make_span("url", m.group(), m.group())))

    # 2. Emails (skip ranges already claimed)
    claimed = {i for s, e, _ in replacements for i in range(s, e)}
    for m in _RE_EMAIL.finditer(text):
        if not any(i in claimed for i in range(m.start(), m.end())):
            replacements.append((m.start(), m.end(), _make_span("email", m.group(), m.group())))
            claimed.update(range(m.start(), m.end()))

    # 3. OTP with keyword — match includes keyword, highlight only the digit group
    has_keyword_otp = False
    for m in _RE_OTP_KEYWORD.finditer(text):
        if not any(i in claimed for i in range(m.start(), m.end())):
            otp_digits = m.group(1)
            full_match = m.group(0)
            # Build replacement: keyword part plain + digits as badge
            keyword_part = str(escape(full_match[: full_match.rfind(otp_digits)]))
            badge = _make_span("otp", otp_digits, otp_digits)
            replacements.append((m.start(), m.end(), keyword_part + badge))
            claimed.update(range(m.start(), m.end()))
            has_keyword_otp = True

    # 4. Phone numbers (only if ≥ _PHONE_MIN_DIGITS digits)
    for m in _RE_PHONE.finditer(text):
        if _digit_count(m.group()) >= _PHONE_MIN_DIGITS:
            if not any(i in claimed for i in range(m.start(), m.end())):
                replacements.append((m.start(), m.end(), _make_span("phone", m.group(), m.group())))
                claimed.update(range(m.start(), m.end()))

    # 5. Standalone OTP digits (only when no keyword OTP found in this message)
    if not has_keyword_otp:
        for m in _RE_OTP_STANDALONE.finditer(text):
            if not any(i in claimed for i in range(m.start(), m.end())):
                replacements.append((m.start(), m.end(), _make_span("otp otp--standalone", m.group(1), m.group(1))))
                claimed.update(range(m.start(), m.end()))

    if not replacements:
        # No entities — just escape and return
        return Markup(escape(text))

    # Sort by start position, build output by interleaving plain escaped segments
    replacements.sort(key=lambda x: x[0])
    parts: list[str] = []
    cursor = 0
    for start, end, html in replacements:
        if start > cursor:
            parts.append(str(escape(text[cursor:start])))
        parts.append(html)
        cursor = end
    if cursor < len(text):
        parts.append(str(escape(text[cursor:])))

    return Markup("".join(parts))
