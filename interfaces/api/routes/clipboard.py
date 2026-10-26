"""
interfaces/api/routes/clipboard.py

Clipboard history for the tray menu. Chat and voice reach the same history
through commands like "clipboard history" (see services/automation/intent.py).
"""

from fastapi import APIRouter
from pydantic import BaseModel

from services.automation.clipboard_history import clipboard_history

router = APIRouter()


class ClipboardHistoryResponse(BaseModel):
    items: list[str]  # newest first


@router.get("/clipboard/history", response_model=ClipboardHistoryResponse)
async def get_clipboard_history():
    return ClipboardHistoryResponse(items=clipboard_history.items())


@router.delete("/clipboard/history")
async def clear_clipboard_history():
    return {"message": clipboard_history.clear()}
