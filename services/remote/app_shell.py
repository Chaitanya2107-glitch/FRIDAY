"""Finite, locally bundled PWA assets. Identity gating is in BridgeSecurity."""
from pathlib import Path

from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parents[2] / 'island' / 'remote-dist'
ASSETS = {'': 'text/html', 'index.html': 'text/html', 'app.js': 'text/javascript',
          'style.css': 'text/css', 'sw.js': 'text/javascript',
          'manifest.webmanifest': 'application/manifest+json',
          'icon-192.png': 'image/png', 'icon-512.png': 'image/png', 'apple-touch-icon.png': 'image/png'}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
       "font-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


def asset(path):
    prefix = '/remote/app/'
    return path[len(prefix):] if path.startswith(prefix) and path[len(prefix):] in ASSETS else None


def response(name):
    path = ROOT / (name or 'index.html')
    if not path.is_file():
        from .routes import refused
        return refused()
    return FileResponse(path, media_type=ASSETS[name], headers={
        'Cache-Control': 'no-store', 'Content-Security-Policy': CSP,
        'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
        'Permissions-Policy': 'camera=(self), microphone=(self), geolocation=()'})
