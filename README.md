# SMS Viewer

A private, self-hosted, **read-only** web viewer for your SMS backups. Your messages stay on your own machine: no cloud, no accounts, no telemetry.

Features: threaded conversations, full-text search, entity recognition (URLs, emails, phone numbers, OTPs with copy-to-clipboard), ZIP/NDJSON import with deduplication, JSON export by date range, installable PWA, and a responsive Material Design 3 inspired UI with light/dark themes.

## Intent: Privacy and Self-Hosting

Many Android apps (banking, e-commerce, UPI and others) ask for SMS permissions. Two of them are particularly exploitable:

- **READ_SMS** lets an app read your entire message history from Android's SMS storage.
- **RECEIVE_SMS** wakes an app the moment a message arrives.

Together, these can be used to profile your finances, purchases, travel and habits. Many apps refuse to work without them, and some also detect rooting or developer options, which blocks the usual workarounds (root, ADB and AppOps).

SMS Viewer is a partial answer to that problem. It lets you take your messages **out of the phone** and still keep them searchable and readable:

1. Back up your SMS with [SMS Import / Export](https://github.com/tmo1/sms-ie), which exports NDJSON/ZIP files.
2. Delete the messages from the phone, so apps with SMS permissions have nothing left to read.
3. Import the backup into SMS Viewer and browse, search and export it on hardware you control.

Design principles:

- **Self-hosted:** runs on your laptop, home server or Termux. Data lives in a local SQLite file (`~/.sms-viewer/sms.db` by default).
- **Private by default:** binds to `127.0.0.1` only, makes no outbound network calls, and has no analytics. The UI uses no external fonts, CDNs or scripts.
- **Read-only:** it views, searches and exports. It never sends or modifies messages on your phone.
- **Protected:** single-user login with hashed passwords, CSRF protection, login rate limiting and hardened HTTP headers.
- **Minimal:** the only dependency is Flask.

> **Limitation:** this reduces what apps can read going forward. It does not remove data already collected by apps that previously had SMS access. Apps that need a live OTP will still need the SMS permission at the moment of use.

## Installation

Requires Python 3.9+.

```bash
pip install sms_viewer-0.1.0-py3-none-any.whl
```

To build the wheel yourself, see [Building from Source](#building-from-source).

## Usage

```bash
# Start with defaults (http://127.0.0.1:5000, db at ~/.sms-viewer/sms.db)
sms-viewer

# Custom host/port
sms-viewer --host 0.0.0.0 --port 8080

# Custom database path
sms-viewer --db-path /path/to/sms.db

# All options
sms-viewer --help
```

### First run

On first run you are redirected to a setup page to create your username and password (minimum 8 characters). After that, log in to access your messages. Then use the **Import** page to upload your backup (`.zip` or `.ndjson`); re-importing the same file is safe because duplicates are skipped.

## Search

On the **Search** page, press Enter to search. The home page filter box narrows conversations as you type.

| Syntax | Meaning |
|---|---|
| `word*` | prefix match |
| `"exact phrase"` | phrase match |
| `address:HDFC`, `body:OTP` | restrict to sender or body |
| `date:2024-05-20` | a single day |
| `date:2024-05`, `date:2024` | a month or a year |
| `date:2024-05-01..2024-05-31` | an inclusive range (either end may be left open) |

Filters combine, e.g. `otp date:2024-05 address:HDFC`. A `date:` filter on its own lists all messages in that period.

## Install as an App (PWA)

SMS Viewer can be installed as a standalone app on Android and desktop browsers (Chrome/Edge: menu, then **Install app** / **Add to Home screen**).

- Browsers only allow installation from a secure origin: `https://...` or `http://localhost`. Plain `http://<LAN-IP>:5000` will not offer install. Serve it over HTTPS (for example via a reverse proxy, Tailscale HTTPS, or Termux with a local proxy).
- The service worker caches only CSS, JS and icons. Messages and API responses are never cached, so no SMS content is stored in the browser. Offline, the app shows a simple "You are offline" page.

## Self-Hosting Notes

- **Stay local:** the default `127.0.0.1` makes the app reachable only from the same machine.
- **Exposing to your network:** `--host 0.0.0.0` makes the app reachable by every device on your network (useful on Termux or a home server). The app serves plain HTTP, so only do this on a trusted network, or put it behind a TLS reverse proxy or VPN such as WireGuard or Tailscale. Do not expose it directly to the internet.
- **Use a long password:** login is rate limited, but the data is sensitive.
- **Back up your data:** copy the SQLite database file (and `.secret_key` next to it, if you want to keep existing sessions).
- **Production server:** `sms-viewer` runs Flask's built-in server, which is fine for a single user. For heavier use, run the app behind a WSGI server such as gunicorn.

## Configuration

| Setting | Flag | Environment variable | Default |
|---|---|---|---|
| Host | `--host` | `SMS_VIEWER_HOST` | `127.0.0.1` |
| Port | `-p`, `--port` | `SMS_VIEWER_PORT` | `5000` |
| Database file | `-d`, `--db-path` | `SMS_VIEWER_DB` | `~/.sms-viewer/sms.db` |
| Session secret | none | `SMS_VIEWER_SECRET` | auto-generated, stored in `.secret_key` beside the database (mode 0600) |

## Building from Source

```bash
pip install build
make build        # cleans, then runs python -m build
# Wheel will be at: dist/sms_viewer-0.1.0-py3-none-any.whl
make clean        # remove build artifacts
```

Without `make`: `python -m build`.

## Development

```bash
pip install -e . pytest
pytest
```
