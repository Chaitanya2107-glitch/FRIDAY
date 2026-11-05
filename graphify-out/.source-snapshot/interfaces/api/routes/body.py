"""
interfaces/api/routes/body.py

For FRIDAY's body (interfaces/body/, the desktop robot): what she's doing right now and what just
happened (services/body_state.py). The body asks a few times a second with the last event id it saw.
"""

from fastapi import APIRouter

from services import body_state

router = APIRouter()


@router.get("/body")
async def body(since: int = 0):
    return {**body_state.snapshot(), "events": body_state.events_since(since), "last": body_state.last_id()}
