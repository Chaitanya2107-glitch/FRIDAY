"""Local endpoint for the two Explorer file-sharing menu options."""

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from services.files.sharing import Channel, ShareStatus, share_file
from services.mind.cognition import cognition

router = APIRouter()


class ShareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: Channel
    path: str = Field(..., min_length=1, max_length=32767)


class ShareResponse(BaseModel):
    success: bool
    message: str
    status: ShareStatus


@router.post("/share/file", response_model=ShareResponse)
async def send_selected_file(request: ShareRequest):
    result = await asyncio.to_thread(share_file, request.path, request.channel)
    cognition.record("action", "file_share", f"File sharing through {request.channel}",
                     status=result.status, public=True)
    return ShareResponse(success=result.success, message=result.message, status=result.status)
