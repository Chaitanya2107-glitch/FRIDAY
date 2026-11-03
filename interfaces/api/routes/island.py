"""Private native-controller link; the webview uses the authenticated WebSocket."""
import hmac
from typing import Annotated
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from services.friday_island_server.config import load_config
from services.friday_island_server.desktop_link import desktop
from services.screen_watch.commands import local_request

router = APIRouter()


def authenticate(token):
    if not local_request.get() or not hmac.compare_digest(token, load_config().connection.token):
        raise HTTPException(403, 'Local authenticated desktop only')


class DesktopState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    listening: bool = False
    wake: bool = False
    conversation: bool = False
    speak: bool = True
    speak_typed: bool = False
    provider: str | None = Field(default=None, max_length=32)
    body: bool = False
    busy: bool = False
    owned: bool = False
    message: str = Field(default='', max_length=500)


class Exchange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    owner: str = Field(min_length=16, max_length=64)
    state: DesktopState
    completed: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(default_factory=list, max_length=24)


@router.post('/island/desktop')
def exchange(body: Exchange, x_friday_island: str = Header(default='', max_length=128)):
    authenticate(x_friday_island)
    try:
        return {'commands': desktop.exchange(body.owner, body.state.model_dump(), body.completed)}
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


class DisplayEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str = Field(pattern='^(response|question|reply_state)$')
    text: str = Field(max_length=4000)
    awaiting_reply: bool = False
    transient: bool = False


@router.post('/island/event')
def display_event(body: DisplayEvent, x_friday_island: str = Header(default='', max_length=128)):
    authenticate(x_friday_island)
    from services.friday_island_server import events
    if not events.connected():
        return {'accepted': False}
    events.publish(body.kind, body.text, awaiting_reply=body.awaiting_reply, transient=body.transient)
    return {'accepted': True}
