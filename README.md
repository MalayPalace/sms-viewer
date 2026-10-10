# SMS Viewer

A production-ready Flask-based web application for viewing SMS backups. Features threaded conversations, full-text search, entity recognition (URLs, emails, phone numbers, OTPs), ZIP/NDJSON import with deduplication, and a Material Design 3 inspired responsive UI.

## Installation

1. Install required dependencies:
```bash
pip install -r requirements.txt
```

2. Install the built package:
```bash
pip install sms_viewer-0.1.0-py3-none-any.whl
```

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

## Data Storage

- **Default database**: `~/.sms-viewer/sms.db`
- **Override via env**: `SMS_VIEWER_DB=/path/to/sms.db sms-viewer`
- **Override via flag**: `sms-viewer --db-path /path/to/sms.db`

## Requirements

- Python 3.9+
- Flask 3.0+

## First Run

On first run, you will be redirected to a setup page to create your username and password. After setup, log in to access the viewer.

## Building from Source

```bash
pip install build
python -m build
# Wheel will be at: dist/sms_viewer-0.1.0-py3-none-any.whl
```
