# SMS Viewer

App is a production-ready Flask-based web application for viewing SMS backups. Features threaded conversations, full-text search, entity recognition (URLs, emails, phone numbers, OTPs), ZIP/NDJSON import with deduplication, and a Material Design 3 inspired responsive UI.

## Intent
SMS Viewer is a viewer only simplistic app created out of Android's Sms privacy in mind. Now a days many of the android's app ask for sms permission (banking/ecommerce/UPI apps). Most exploitable permissions are: 
- read-sms permission: which allow app to read entire sms list from the android sms storage. 
- receive-sms permission: which invokes the app's intent as soon as sms arrives.

I feel using these sms, an app can profile entire lifestyle/usage of a person and as a Android User we are hopeless in preventing it because some apps don't without those permission. Ofcourse root and ADB + AppOps are the possible ways which can prevent it but those app specifically check for root/developer options settings and dont allow it.    

To circumvent it(atleast part of it) created this app which serves a viewer only sms app by which you can backup sms and delete sms from android phones and import it for viewing and search functionality. Messages exported through https://github.com/tmo1/sms-ie app can be imported directly with this app.

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
