# SMS Viewer — Implementation Plan

> **Version**: 2026-09-12 (v1)
> **Status**: Draft — Awaiting User Approval

---

## 1. Problem Statement

Build a production-ready Python Flask web application that acts as a read-only SMS viewer. It imports SMS data from ZIP/NDJSON backups, stores them in SQLite, and presents them in a threaded material-design UI. The app must work on both desktop browsers and Android via Termux, and be distributed as a single `.whl` file.

---

## 2. Decisions Log (from clarification)

| # | Question | Decision |
|---|---------|----------|
| 1 | Database fields | Store only essential fields: `_id`, `thread_id`, `address`, `date`, `date_sent`, `type`, `body`, `read` |
| 2 | Thread conversation | Show both sent (type=2) and received (type=1) — full conversation view |
| 3 | Thread grouping | Group by `address` (sender/recipient) |
| 4 | Authentication | Simple username/password (single-user) |
| 5 | OTP recognition | Keyword-preceded numbers get priority + standalone 4-8 digit codes |
| 6 | CLI entry point | `sms-viewer` command with `--port`, `--host` flags (default port 5000) |
| 7 | Dark mode | Both light and dark mode with toggle switch |
| 8 | Search library | SQLite FTS5 (built-in, zero extra deps) |
| 9 | ZIP import | Expect exactly one NDJSON file per ZIP |
| 10 | Default port | Configurable via CLI, default 5000 |

---

## 3. Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Backend | **Flask 3.x** | Lightweight, Jinja2 built-in, well-suited for single-user tools |
| Templates | **Jinja2** (bundled with Flask) | First-class Flask integration |
| Database | **SQLite3** (stdlib) | Zero-dependency, portable, embeddable in wheel |
| Full-Text Search | **SQLite FTS5** | Built into SQLite, supports prefix/phrase/word search, zero deps |
| CLI | **Click** (bundled with Flask) | Flask already depends on Click — no extra dependency |
| Auth | **Flask sessions** + **werkzeug.security** | `generate_password_hash` / `check_password_hash` — no extra deps |
| Packaging | **setuptools + wheel** via `pyproject.toml` | Standard PEP 517/621 compliant packaging |
| CSS | **Vanilla CSS** | Material Design 3 inspired, custom properties for theming |
| JS | **Vanilla JavaScript** | No framework overhead, progressive enhancement |

### Dependencies (total: 1 direct)

```
Flask>=3.0.0
```

> Flask transitively brings: Jinja2, Click, Werkzeug, MarkupSafe, itsdangerous, blinker. No other PyPI packages needed.

---

## 4. Project Structure

```
sms-viewer/
├── pyproject.toml                  # Build config, dependencies, entry point
├── MANIFEST.in                     # sdist inclusion rules
├── README.md                       # Project documentation
├── docs/
│   └── implementation_plan_2026-09-12.md   # Implementation plan
├── src/
│   └── sms_viewer/
│       ├── __init__.py             # Package version
│       ├── app.py                  # Flask application factory
│       ├── cli.py                  # CLI entry point (sms-viewer command)
│       ├── database/               # Database Layer
│       │   ├── __init__.py
│       │   ├── db.py               # Path resolution, init_db, schema migration
│       │   └── db_helper.py        # Central DatabaseHelper class for all DB queries & bulk inserts
│       ├── feature/                # Feature Modules Layer
│       │   ├── __init__.py
│       │   ├── importer.py         # ZIP/NDJSON import pipeline (uses db_helper)
│       │   ├── exporter.py         # JSON export module (uses db_helper)
│       │   ├── recognizer.py       # Entity recognition (URL, email, phone, OTP)
│       │   └── search.py           # FTS5 search engine (uses db_helper)
│       ├── rest/                   # REST API & Auth Layer
│       │   ├── __init__.py
│       │   ├── api.py              # REST API blueprint routes
│       │   └── auth.py             # Auth blueprint routes & login_required decorator
│       ├── views/                  # HTML Views Layer
│       │   ├── __init__.py
│       │   └── views.py            # Page views blueprint routes
│       ├── static/
│       │   ├── css/
│       │   │   └── style.css       # Material Design 3 inspired styles
│       │   └── js/
│       │       └── app.js          # Client-side interactivity
│       └── templates/
│           ├── base.html           # Base layout with nav, theme toggle
│           ├── login.html          # Authentication page
│           ├── threads.html        # Thread list view (main screen)
│           ├── conversation.html   # Individual thread/conversation view
│           ├── search_results.html # Search results page
│           ├── import.html         # Import page with file upload
│           └── export.html         # Export page with date pickers
```

---

## 5. Database Schema

### Table: `messages`

```sql
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    original_id     TEXT,                    -- _id from NDJSON
    thread_id       TEXT,                    -- thread_id from NDJSON (stored but not used for grouping)
    address         TEXT NOT NULL,           -- sender/recipient identifier
    date            INTEGER NOT NULL,        -- epoch milliseconds (from NDJSON)
    date_sent       INTEGER,                -- epoch milliseconds (from NDJSON)
    read            INTEGER DEFAULT 1,       -- 0=unread, 1=read
    status          INTEGER DEFAULT -1,      -- SMS status
    type            INTEGER DEFAULT 1,       -- 1=received, 2=sent
    body            TEXT NOT NULL,           -- message content
    body_hash       TEXT NOT NULL,           -- SHA-256 hash of body for dedup
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- Deduplication constraint
    UNIQUE(date, address, body_hash)
);

CREATE INDEX IF NOT EXISTS idx_messages_address ON messages(address);
CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
CREATE INDEX IF NOT EXISTS idx_messages_address_date ON messages(address, date DESC);
```

### Table: `messages_fts` (FTS5 Virtual Table)

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    body,
    address,
    content='messages',
    content_rowid='id',
    tokenize='unicode61'
);
```

FTS5 triggers to keep the index in sync:

```sql
-- After INSERT
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, body, address) VALUES (new.id, new.body, new.address);
END;

-- After DELETE
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, body, address) VALUES('delete', old.id, old.body, old.address);
END;

-- After UPDATE
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, body, address) VALUES('delete', old.id, old.body, old.address);
    INSERT INTO messages_fts(rowid, body, address) VALUES (new.id, new.body, new.address);
END;
```

### Table: `users` (Single-user auth)

```sql
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Table: `import_log` (Track imports)

```sql
CREATE TABLE IF NOT EXISTS import_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    filename        TEXT NOT NULL,
    records_total   INTEGER DEFAULT 0,
    records_imported INTEGER DEFAULT 0,
    records_skipped INTEGER DEFAULT 0,
    imported_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 6. Core Components Design

### 6.1 Import Pipeline (`importer.py`)

```
ZIP Upload → Extract → Validate NDJSON → Parse Lines → Deduplicate → Bulk Insert → FTS Sync
```

**Deduplication logic:**
1. For each NDJSON line, compute `body_hash = SHA-256(body.strip())`
2. Use `INSERT OR IGNORE` with the `UNIQUE(date, address, body_hash)` constraint
3. Track counts: total, imported, skipped (duplicates)

**Key considerations:**
- Process NDJSON line-by-line (streaming) to handle large files without loading all into memory
- Use database transactions with batch commits (every 1000 records) for performance
- Validate each line: require `address`, `date`, `body` fields — skip malformed lines
- Store import metadata in `import_log` table for audit trail

### 6.2 Export Pipeline (`exporter.py`)

- Accept `from_date` and `to_date` from UI (ISO 8601 date strings)
- Convert to epoch milliseconds for SQLite query
- Query messages within date range
- JSON structure: **TBD by user in next phase** (placeholder structure for now)
- Serve as downloadable `.json` file with `Content-Disposition: attachment`

### 6.3 Search Engine (`search.py`)

**SQLite FTS5 capabilities used:**
- **Full-text search**: `SELECT * FROM messages_fts WHERE messages_fts MATCH 'bank transaction'`
- **Prefix search**: `'trans*'` matches "transaction", "transfer", etc.
- **Phrase search**: `'"credit card"'` matches exact phrase
- **Column filtering**: `'body:OTP'` searches only body, `'address:HDFC'` searches only sender

**Search API flow:**
1. User enters query in search bar
2. JavaScript sends `GET /api/search?q=<query>&page=1`
3. Backend sanitizes query, runs FTS5 MATCH
4. Returns paginated results with highlighted snippets (using FTS5 `highlight()` function)
5. Frontend renders results with thread context

### 6.4 Entity Recognizer (`recognizer.py`)

Regex-based pattern detection applied during template rendering via Jinja2 filters:

| Entity | Pattern | Action on Click |
|--------|---------|-----------------|
| **URL** | `https?://[^\s<>"{}|\\^` `` ` `` \[\]]+` | Copy to clipboard |
| **Email** | `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}` | Copy to clipboard |
| **Phone** | `(?:\+?\d{1,3}[-.\s]?)?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}` (≥7 digits total) | Copy to clipboard |
| **OTP (keyword)** | `(?:OTP\|otp\|code\|PIN\|pin\|verification\|password)[\s:is]*(\d{4,8})` | Copy to clipboard (highlighted badge) |
| **OTP (standalone)** | `\b(\d{4,8})\b` (only when no keyword OTP found, context-aware) | Copy to clipboard (subtle highlight) |

**Implementation:** A custom Jinja2 filter `{{ message.body | highlight_entities }}` that wraps detected entities in `<span class="entity entity--url" data-copy="..." onclick="copyToClipboard(this)">` elements.

### 6.5 Authentication (`auth.py`)

- **First-run setup**: If no user exists in `users` table, show a one-time setup page to create username/password
- **Login**: Session-based with `werkzeug.security.check_password_hash`
- **Session**: Flask's built-in signed cookie sessions with a `SECRET_KEY`
- **Protection**: All routes except `/login` and `/setup` require `@login_required` decorator
- **Logout**: Clear session, redirect to login

---

## 7. UI / Frontend Design

### 7.1 Design System (CSS Custom Properties)

```css
:root {
    /* Light theme */
    --bg-primary: #f5f5f5;
    --bg-surface: #ffffff;
    --bg-surface-variant: #e8e8e8;
    --text-primary: #1a1a2e;
    --text-secondary: #666666;
    --accent: #6750a4;            /* MD3 Primary */
    --accent-container: #eaddff;
    --entity-url: #4fc3f7;
    --entity-email: #81c784;
    --entity-phone: #ffb74d;
    --entity-otp: #ff8a65;
}

[data-theme="dark"] {
    --bg-primary: #1a1a2e;
    --bg-surface: #252540;
    --bg-surface-variant: #2d2d4a;
    --text-primary: #e8e8e8;
    --text-secondary: #a0a0b0;
    --accent: #d0bcff;
    --accent-container: #4f378b;
    /* ... entity colors adjusted for dark bg */
}
```

### 7.2 Views

#### Thread List (Main Screen)
- Header bar with app title + settings gear icon
- Search bar below header (sticky on scroll)
- Scrollable list of conversation threads
- Each thread row: circular colored avatar (first letter), sender name, last message preview (truncated), timestamp, unread badge
- Threads sorted by latest message date (most recent first)
- Message count badge on each thread
- Pagination: infinite scroll or "Load More" button
- FAB (floating action button) for import at bottom-right

#### Conversation Detail View
- Header: back arrow + sender name
- Chat-bubble layout:
  - Received messages (type=1): left-aligned, dark surface color bubbles
  - Sent messages (type=2): right-aligned, accent color bubbles
- Each bubble: body text with entity highlighting, timestamp below
- Date separators between messages from different days
- Scroll to bottom by default (latest messages)
- Entity elements are visually distinct with colored badges and copy-on-click tooltip

#### Search Results
- Search input at top
- Real-time results as user types (debounced 300ms)
- Results show: sender name, highlighted matching text snippet, timestamp
- Click result → navigates to conversation, scrolled to that message

#### Import Page
- Drag-and-drop zone for ZIP file upload
- Progress bar during import
- Summary after import: total records, imported, skipped (duplicates)
- Import history table (from `import_log`)

#### Export Page
- Date range picker (from/to)
- Preview of records count in selected range
- "Export" button → downloads JSON file

#### Login / Setup Page
- Clean centered card with username/password fields
- First-run: "Create Account" form
- Subsequent: "Login" form

### 7.3 Responsive Breakpoints

```css
/* Mobile-first: Default styles target mobile (< 640px) */
/* Tablet */
@media (min-width: 640px) { ... }
/* Desktop */
@media (min-width: 1024px) { ... }
/* Wide desktop */
@media (min-width: 1280px) { ... }
```

- **Mobile (< 640px)**: Full-width thread list, full-width conversation. Optimized for Termux/Android browsers.
- **Tablet (640-1024px)**: Same as mobile but with more padding.
- **Desktop (> 1024px)**: Side-by-side layout possible (thread list on left, conversation on right).

---

## 8. API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Thread list page |
| `GET` | `/thread/<address>` | Conversation view for a sender |
| `GET` | `/search` | Search results page |
| `GET` | `/import` | Import page |
| `GET` | `/export` | Export page |
| `GET` | `/login` | Login page |
| `POST` | `/login` | Process login |
| `GET` | `/setup` | First-run setup page |
| `POST` | `/setup` | Create initial user |
| `POST` | `/logout` | Logout |
| `GET` | `/api/search?q=<query>&page=<n>` | JSON search results |
| `GET` | `/api/threads?page=<n>` | JSON thread list (for infinite scroll) |
| `GET` | `/api/messages/<address>?page=<n>` | JSON messages for a thread |
| `POST` | `/api/import` | Handle ZIP file upload |
| `GET` | `/api/export?from=<date>&to=<date>` | Download exported JSON |

---

## 9. Packaging (`pyproject.toml`)

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "sms-viewer"
version = "0.1.0"
description = "A Flask-based SMS backup viewer with threaded conversations and full-text search"
readme = "README.md"
requires-python = ">=3.9"
license = {text = "MIT"}
dependencies = [
    "Flask>=3.0.0",
]

[project.scripts]
sms-viewer = "sms_viewer.cli:main"

[tool.setuptools]
include-package-data = true

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
sms_viewer = [
    "templates/**/*",
    "templates/*",
    "static/**/*",
    "static/*",
]
```

### CLI Usage

```bash
# Install
pip install sms_viewer-0.1.0-py3-none-any.whl

# Run with defaults (port 5000, host 127.0.0.1, db at ~/.sms-viewer/sms.db)
sms-viewer

# Custom options
sms-viewer --host 0.0.0.0 --port 8080 --db-path /data/sms.db

# Help
sms-viewer --help
```

### Data Directory

- **Default**: `~/.sms-viewer/sms.db`
- **Override**: `--db-path` CLI flag or `SMS_VIEWER_DB` environment variable
- **First run**: Directory and database are created automatically

---

## 10. Implementation Phases

### Phase 1: Foundation (Core Infrastructure) - ✅ COMPLETE
1. Set up project structure (`src/` layout)
2. Create `pyproject.toml` and `MANIFEST.in`
3. Implement database module (`db.py`) — schema creation, connection management
4. Implement Flask app factory (`app.py`)
5. Implement CLI entry point (`cli.py`)
6. Create base template (`base.html`) with theme toggle
7. Create CSS design system (`style.css`)
8. Verify wheel builds and installs correctly

### Phase 2: Import & Data Layer - ✅ COMPLETE
1. Implement NDJSON parser and import pipeline (`importer.py`)
2. Implement ZIP extraction and validation
3. Implement deduplication logic (SHA-256 hash + UNIQUE constraint)
4. Create import UI page with drag-and-drop upload
5. Implement import log tracking
6. Test with provided sample data

### Phase 3: Thread Views & UI ✅ COMPLETE
1. ✅ Implement thread list view — query, group by address, sort by latest
2. ✅ Implement conversation detail view — chronological messages with bubbles
3. ✅ Create responsive CSS for both views
4. ✅ Implement infinite scroll / pagination (client-side + API)
5. ✅ Add date separators in conversation view
6. ✅ Polish Material Design 3 aesthetics, animations, transitions
7. ✅ Automated tests: 7/7 passing (`tests/test_views.py`)
8. ✅ Wheel built and verified: `sms_viewer-0.1.0-py3-none-any.whl`

### Phase 4: Search & Entity Recognition ✅ COMPLETE
1. ✅ FTS5 virtual table set up and sync triggers in place (`init_db`)
2. ✅ Search backend: query sanitization, FTS5 MATCH, pagination, `<mark>` snippet highlighting (`feature/search.py`)
3. ✅ Search UI: result cards with avatars, snippets, direction badges, pagination, FTS5 tips (`search_results.html`)
4. ✅ Entity recognizer: URL, email, phone (≥7 digits), OTP-with-keyword, OTP-standalone (`feature/recognizer.py`)
5. ✅ Jinja2 `highlight_entities` filter registered in `app.py`; applied to conversation bubbles
6. ✅ Copy-to-clipboard via `data-copy` attribute on entity `<span>` elements; toast feedback
7. ✅ `/api/search` endpoint with pagination + enriched fields (`rest/api.py`)
8. ✅ SSR `/search` page view with query params + pagination context (`views/views.py`)
9. ✅ Search icon added to navbar (`base.html`)
10. ✅ Tests: 47/47 passing (`tests/test_search.py` + all prior tests)

### Phase 5: Authentication & Export ✅ COMPLETE
1. ✅ Auth blueprint — setup, login, logout, session management (`rest/auth.py`)
2. ✅ `@login_required` on all page routes; `/api/*` returns JSON 401 when unauthenticated (`rest/api.py`)
3. ✅ Export pipeline — inclusive date range → epoch ms, JSON download with `Content-Disposition` (`feature/exporter.py`, `/api/export`, `/api/export/count`)
4. ✅ Export UI page with date pickers and live record count (`export.html`)
5. ✅ SECRET_KEY: explicit arg > `SMS_VIEWER_SECRET` env > auto-generated and persisted to `.secret_key` (mode 0600) beside the DB (`app.py`)
6. ✅ Tests: 67/67 passing (`tests/test_auth_export.py` + all prior tests)

### Phase 6: Polish & Production Readiness ✅ COMPLETE
1. ✅ Error handling — 400/403/404/405/413/429/500 pages (`templates/errors/`), JSON errors for `/api/*`, flash messages in `base.html`
2. ✅ Security hardening (`security.py`) — session-bound CSRF tokens (forms + `X-CSRFToken` header), login rate limiting (5 failures / 5 min per IP → 429), username/password length limits, upload size cap, CSP / `X-Frame-Options` / `nosniff` / `Referrer-Policy` headers, HttpOnly + SameSite=Lax cookies, `no-store` on auth/API responses
3. ✅ Performance — existing composite indexes retained (`address,date`), static asset caching (`SEND_FILE_MAX_AGE_DEFAULT`); infinite scroll/pagination from Phase 3
4. ✅ Accessibility — skip link, focus-visible outlines, `prefers-reduced-motion`, ARIA live regions/alerts, pinch-zoom re-enabled (removed `user-scalable=no`)
5. ✅ Responsive layout retained from Phase 3 (mobile-first breakpoints at 640px / 1024px); not re-verified in a real browser
6. ✅ Wheel built and verified to include new modules/templates: `dist/sms_viewer-0.1.0-py3-none-any.whl`
7. ✅ Tests: 84/84 passing (`tests/test_hardening.py` + all prior tests)

---

## 11. UI Reference Mockups

### Thread List View
![Thread list mockup showing Material Design 3 inspired dark mode with sender avatars, message previews, and search bar](/home/malay/.gemini/antigravity/brain/db6d5cf6-2365-4bc1-80a8-8c8f50d65b5c/thread_list_mockup_1789195776531.png)

### Conversation Detail View
![Conversation detail mockup showing chat bubbles with highlighted URLs, phone numbers, and OTP codes](/home/malay/.gemini/antigravity/brain/db6d5cf6-2365-4bc1-80a8-8c8f50d65b5c/thread_detail_mockup_1789195791179.png)

---

## 12. Open Questions

> [!IMPORTANT]
> **Export JSON structure**: You mentioned defining the JSON export structure in the next phase. For Phase 5, I'll implement a default structure that mirrors the database fields, which you can customize later. Is that acceptable?

> [!NOTE]
> **Termux-specific considerations**: On Termux, the default data directory `~/.sms-viewer/` maps to Termux's home. The app will bind to `0.0.0.0` when deploying on Android to allow local network access. Any additional Termux requirements?

---

## 13. Verification Plan

### Automated Tests
```bash
# Build wheel
python -m build

# Verify wheel contents include templates and static files
unzip -l dist/sms_viewer-0.1.0-py3-none-any.whl

# Install in isolated venv and test
python -m venv test_env
source test_env/bin/activate
pip install dist/sms_viewer-0.1.0-py3-none-any.whl
sms-viewer --help

# Run with sample data
sms-viewer --port 5000 --no-browser
```

### Manual Verification
- Import sample ZIP/NDJSON data
- Verify deduplication on re-import
- Navigate thread list and conversation views
- Test search with full-text, prefix, and phrase queries
- Verify entity recognition (URLs, emails, phones, OTPs) and copy-to-clipboard
- Test responsive layout on mobile viewport (Chrome DevTools)
- Test export with date range
- Test login/logout flow
- Verify dark/light mode toggle persistence
