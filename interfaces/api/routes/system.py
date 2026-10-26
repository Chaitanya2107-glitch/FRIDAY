"""System controls use the shared command router; remaining routes expose stats and notifications."""

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.config import config
from core.errors import FridayError
from services.automation import modes, system_stats
from services.spotify import auth as spotify_auth
from services.proactive import buttons


router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────────────

class SystemRequest(BaseModel):
    command: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Natural language command (e.g. 'open chrome', 'search cats on google')"
    )
    provider: str | None = Field(None, description="Override active provider")
    speak: bool = Field(True, description="Whether FRIDAY should speak the result")


class SystemResponse(BaseModel):
    command: str
    action: str
    result: str
    success: bool


@router.post("/system", response_model=SystemResponse)
async def system_control(request: SystemRequest):
    """Use the same local and AI command routing as chat and voice."""
    from services.automation import intent
    from services.mind.replies import REMARKS

    # This endpoint cannot complete chat/voice's yes/no confirmation exchange.
    if intent.is_awaiting_confirmation():
        raise FridayError("An action needs confirmation in chat or voice. Answer it there first.")
    result = await intent.try_system_action(request.command, request.provider or config.ACTIVE_PROVIDER)
    if intent.is_awaiting_confirmation():
        intent.cancel_pending_confirmation()
        raise FridayError("This action needs confirmation. Ask FRIDAY in chat or voice instead.")
    message = result.message if result else REMARKS["unmatched"]
    if request.speak and result and result.speech != "":
        from interfaces.api.routes.voice import _speak_in_background
        _speak_in_background(result.speech or message)
    return SystemResponse(command=request.command, success=bool(result and result.success),
                          action="system_control" if result else "unknown", result=message)


@router.get("/system/stats")
async def get_system_stats():
    """Short CPU / RAM / battery / GPU / disk lines, for the tray menu."""
    return {"lines": await asyncio.to_thread(system_stats.menu_lines)}


class ModeStatus(BaseModel):
    name: str | None
    quiet: bool | None = None


class SpotifyStatus(BaseModel):
    configured: bool | None
    connected: bool | None


class RuntimeStatus(BaseModel):
    mode: ModeStatus
    spotify: SpotifyStatus


@router.get("/system/status", response_model=RuntimeStatus)
def get_runtime_status():
    """Read actual local mode and saved Spotify connection; never infer state with AI."""
    try:
        state = modes.active(strict=True)
        mode = ModeStatus(name=state['name'] if state else 'normal', quiet=bool(state and state.get('quiet')))
    except Exception:
        mode = ModeStatus(name=None)
    try:
        spotify = SpotifyStatus(configured=spotify_auth.is_configured(), connected=spotify_auth.is_connected())
    except (ValueError, OSError):
        spotify = SpotifyStatus(configured=None, connected=None)
    return RuntimeStatus(mode=mode, spotify=spotify)


class NotifyResponse(BaseModel):
    token: str = Field(..., max_length=64)
    answer: str = Field(..., max_length=12)


class BarOutcome(BaseModel):
    offered: list[str] = Field(default_factory=list, max_length=10)
    sent: str | None = Field(None, max_length=4000)  # only compared with the guesses, never saved


@router.get("/predict/bar")
async def bar_suggestions():
    """The command bar's guesses when it opens empty (services/activity/predict.py)."""
    from services.activity import predict
    from services.activity.log import activity_log

    return {"suggestions": await asyncio.to_thread(predict.bar_suggestions, activity_log)}


@router.post("/predict/bar/outcome")
async def bar_outcome(body: BarOutcome):
    """Which guess was used (or none) — saved as a training example."""
    from services.activity import predict
    from services.activity.log import activity_log

    await asyncio.to_thread(predict.bar_outcome, body.offered, body.sent, activity_log)
    return {"ok": True}


@router.post("/notify/respond")
async def notification_button(request: NotifyResponse):
    """A notification button was clicked (interfaces/protocol_handler.py). Only tokens FRIDAY issued count."""
    return {"message": await asyncio.to_thread(buttons.respond, request.token, request.answer)}
