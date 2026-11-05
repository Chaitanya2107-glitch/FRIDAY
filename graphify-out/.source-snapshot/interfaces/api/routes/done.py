"""
interfaces/api/routes/done.py

Where Claude Code's hooks and the PowerShell prompt report finished work (services/watch/done.py).
Only this laptop can reach the API (app.py). Replies are empty on purpose: Claude Code adds a
UserPromptSubmit hook's output to the conversation.
"""

from fastapi import APIRouter, BackgroundTasks, Body, Response
from pydantic import BaseModel, Field

from services.proactive import buttons
from services import body_state
from services.watch import done

router = APIRouter()


class TerminalCommand(BaseModel):
    command: str = Field(..., max_length=10_000)
    seconds: float = Field(..., ge=0)
    ok: bool = True


@router.post("/done/claude", status_code=204)
async def claude_hook(background: BackgroundTasks, payload: dict = Body(...)):
    body_state.claude(payload)  # thinking dots while Claude works, a jump when it's done
    text = done.claude_event(payload)
    if text:
        background.add_task(done.notify, text, True)  # after the reply: the hook never waits on the toast
    return Response(status_code=204)


@router.post("/done/terminal", status_code=204)
async def terminal_hook(report: TerminalCommand, background: BackgroundTasks):
    text = done.terminal_event(report.command, report.seconds, report.ok)
    if text:  # a failed command gets [Explain]: FRIDAY reads the terminal on screen (buttons.py)
        links = None if report.ok else buttons.offer("explain", command=report.command[:200])
        background.add_task(done.notify, text, True, links)
    return Response(status_code=204)
