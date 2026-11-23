"""
Progressive Web App support: web manifest, service worker and offline page.

The service worker caches only static assets (CSS/JS/icons) and the offline
page. Message pages and API responses are never cached, so no SMS content is
ever stored in the browser's cache.
"""

import json

from flask import Blueprint, current_app, jsonify, render_template, url_for

pwa_bp = Blueprint("pwa", __name__)

THEME_COLOR = "#6750a4"
CACHE_VERSION = "v1"

SW_SOURCE = """\
const CACHE = 'sms-viewer-%(version)s';
const PRECACHE = %(precache)s;

self.addEventListener('install', (event) => {
    event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    const req = event.request;
    if (req.method !== 'GET') return;
    const url = new URL(req.url);
    if (url.origin !== self.location.origin) return;

    // Static assets: network first (always fresh), cache as offline fallback
    if (url.pathname.startsWith('/static/')) {
        event.respondWith(
            fetch(req)
                .then((res) => {
                    const copy = res.clone();
                    caches.open(CACHE).then((c) => c.put(req, copy));
                    return res;
                })
                .catch(() => caches.match(req))
        );
        return;
    }

    // Pages: never cached (private data); show the offline page when unreachable
    if (req.mode === 'navigate') {
        event.respondWith(fetch(req).catch(() => caches.match('%(offline)s')));
    }
});
"""


@pwa_bp.route("/manifest.webmanifest")
def manifest():
    """Web app manifest enabling "Install app" / "Add to Home screen"."""
    icon = lambda name: url_for("static", filename=f"icons/{name}")  # noqa: E731
    body = {
        "name": "SMS Viewer",
        "short_name": "SMS Viewer",
        "description": "Private, self-hosted, read-only SMS backup viewer",
        "id": "/",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#f0eff5",
        "theme_color": THEME_COLOR,
        "icons": [
            {"src": icon("icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": icon("icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": icon("icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    response = jsonify(body)
    response.mimetype = "application/manifest+json"
    return response


@pwa_bp.route("/sw.js")
def service_worker():
    """Service worker, served from the root so its scope covers the whole app."""
    precache = [
        url_for("pwa.offline"),
        url_for("static", filename="css/style.css"),
        url_for("static", filename="js/app.js"),
        url_for("static", filename="icons/icon-192.png"),
    ]
    source = SW_SOURCE % {
        "version": CACHE_VERSION,
        "precache": json.dumps(precache),
        "offline": url_for("pwa.offline"),
    }
    response = current_app.response_class(source, mimetype="text/javascript")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


@pwa_bp.route("/offline")
def offline():
    """Static offline fallback page (public, contains no user data)."""
    return render_template("offline.html")
