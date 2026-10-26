"""
interfaces/api/routes/mind.py

For the tray: the "Let FRIDAY talk on her own" switch, and her questions as they happen
(a long poll — the tray opens the command bar and the mic the moment she asks).
"""

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from services.mind import talk

router = APIRouter()
MAX_WAIT_SECONDS = 30


@router.get('/mind/brain')
async def brain_status():
    from services.mind.inquiry import inquiry
    from services.mind.cognitive_runtime import running
    status = await asyncio.to_thread(inquiry.status)
    from services.mind.consolidation import consolidation
    from services.mind.review_metrics import latest
    return {'attention_running': running(), 'inquiry': status,
            'consolidation': await asyncio.to_thread(consolidation.status),
            'local_review': await asyncio.to_thread(latest)}


@router.get('/mind/situation')
async def get_situation():
    from services.mind.temporal_memory import situation
    return await asyncio.to_thread(situation)


@router.get('/mind/life')
async def get_life_state():
    from services.mind.life_state import current
    return await asyncio.to_thread(current)


@router.get('/mind/outcomes')
async def get_action_outcomes():
    from services.mind.outcome_learning import outcome_learning
    return await asyncio.to_thread(outcome_learning.context)


@router.get('/mind/situation/history')
async def get_situation_history(subject: str):
    from services.mind.temporal_memory import temporal_memory
    return {'revisions': await asyncio.to_thread(temporal_memory.history, subject)}


@router.get("/mind/layers")
async def get_layers():
    from services.mind.layers import inventory
    return {"layers": inventory()}


@router.get("/mind/workspace")
async def get_workspace():
    from services.mind.workspace import workspace
    return await asyncio.to_thread(workspace.context)


@router.get("/mind/reasoning")
async def get_reasoning():
    from services.mind.reasoning_store import reasoning_store
    return await asyncio.to_thread(reasoning_store.context)


@router.get("/mind/notifications")
async def get_notification_status():
    from services.mind.notification_status import snapshot
    return await asyncio.to_thread(snapshot)


class TalkSwitch(BaseModel):
    on: bool


@router.get("/mind/talk", response_model=TalkSwitch)
async def get_talk():
    return TalkSwitch(on=talk.is_on())


@router.post("/mind/talk", response_model=TalkSwitch)
async def set_talk(switch: TalkSwitch):
    talk.set_on(switch.on)
    return TalkSwitch(on=switch.on)


@router.get("/mind/ask")
async def next_ask(wait: float = 25):
    """Her next question, or {"question": null} after `wait` seconds."""
    try:
        question = await asyncio.wait_for(talk.asks().get(), timeout=min(max(wait, 0), MAX_WAIT_SECONDS))
    except asyncio.TimeoutError:
        question = None
    return {"question": question}
