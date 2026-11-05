"""
interfaces/api/routes/files.py

File search status and controls for the tray. Chat and voice reach the same
search through "find my …" and questions about the files
(services/files/assistant.py).
"""

import asyncio

from fastapi import APIRouter, Query

from core.config import config
from services.files import assistant
from services.files.index import file_index
from services.files.search import find_files

router = APIRouter()


@router.get("/files/status")
async def file_search_status():
    stats = await asyncio.to_thread(file_index.stats)
    return {"enabled": config.FILE_SEARCH_ENABLED,
            "folders": [str(f) for f in config.file_search_folders()], **stats}


@router.post("/files/rescan")
async def rescan_files():
    return {"message": assistant.rescan()}


@router.get("/files/search")
async def search_files(q: str = Query(..., min_length=1, max_length=200)):
    hits = await asyncio.to_thread(find_files, q)
    return {"results": [{"name": h.name, "path": h.path} for h in hits]}
