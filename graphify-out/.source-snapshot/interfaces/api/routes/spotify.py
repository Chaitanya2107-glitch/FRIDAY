"""
interfaces/api/routes/spotify.py

Where Spotify sends the browser back after "connect Spotify" (the redirect URI
registered in the Spotify app: config.SPOTIFY_REDIRECT_URI), plus a status check.
The login itself lives in services/spotify/auth.py.
"""

import asyncio
from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from services.spotify import auth

router = APIRouter()

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>F.R.I.D.A.Y — Spotify</title></head>
<body style="font-family:system-ui,sans-serif;background:#0b0f14;color:#e6edf3;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
<div style="max-width:32rem;padding:0 16px;text-align:center"><h2>{title}</h2><p>{text}</p></div>
</body></html>"""


def _page(title: str, text: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(PAGE.format(title=escape(title), text=escape(text)), status_code=status_code)


@router.get("/spotify/callback", response_class=HTMLResponse, include_in_schema=False)
async def spotify_callback(code: str = "", state: str = "", error: str = ""):
    if error or not code:
        # e.g. "access_denied" when the user pressed Cancel
        return _page("Spotify wasn't connected", f"Spotify said: {error or 'no login code'}. "
                     "Say \"connect Spotify\" to try again.", 400)
    try:
        await asyncio.to_thread(auth.finish_login, code, state)
    except auth.SpotifyError as e:
        return _page("Spotify wasn't connected", str(e), 400)
    return _page("Spotify connected", "FRIDAY can now play your music. You can close this tab.")


@router.get("/spotify/status")
async def spotify_status():
    return {"configured": auth.is_configured(), "connected": auth.is_connected()}
