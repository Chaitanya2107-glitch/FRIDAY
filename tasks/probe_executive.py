"""One bounded configured-provider trial using synthetic owner evidence and temporary SQLite."""
import asyncio
import json
import logging
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.config import config
from core.logger import logger
for handler in list(logger.handlers):
    logger.removeHandler(handler)
    if isinstance(handler, logging.FileHandler):
        handler.close()

from providers import failover
from services.memory import notes
from services.memory.semantic import semantic_memory
from services.proactive import timetable, deadlines
from services.mind import cognition_context
from services.mind.cognition import cognition
from services.mind.workspace import workspace
from services.mind.reasoning_store import reasoning_store
from services.mind.executive import ExecutiveControl


async def trial(root):
    config.AI_ASSIST_ONLY = config.REASONING_ENABLED = config.COGNITION_ENABLED = config.COGNITIVE_REVIEW_ENABLED = True
    # Never start a local model server for a development probe.
    config.OLLAMA_AUTO_START = False
    cognition.path = root / "cognition.db"
    config.MEMORY_DB_PATH = str(root / "commands.db")
    semantic_memory.db_path = str(root / "memory.db")
    notes.path, timetable.path, deadlines.path = root / "notes.json", root / "classes.json", root / "deadlines.json"
    cognition_context.live_state = lambda: {"activity": "coding", "away": False, "mode_active": False,
        "waiting_for_answer": False, "speaking": False, "listening": False, "active_operations": []}
    goal = workspace.add_goal("Verify a synthetic demo project", "high")
    task = workspace.start_task("Review the synthetic demo router", goal)
    workspace.focus("task", task)
    runner = ExecutiveControl(cognition)
    responses = []
    original = failover.complete_with_failover
    async def observed(*args, **kwargs):
        response = await original(*args, **kwargs)
        responses.append({"provider": response.provider, "content": response.content})
        return response
    failover.complete_with_failover = observed
    now = datetime.now()
    result = await runner.review(now)
    repeated = await runner.review(now + timedelta(minutes=6) if result["status"] == "completed" else now)
    context = reasoning_store.context(now)
    with workspace._db() as conn:
        task_state = workspace._task(conn, task)
    return {"status": result["status"], "repeat_status": repeated["status"],
            "conclusions": len(context["conclusions"]), "facts_created": len(context["facts"]),
            "source_task_status": task_state["status"], "source_task_cursor": task_state["cursor"],
            "source_task_steps": task_state["steps"], "budget_used": runner.status(now)["reviews_this_hour"],
            "synthetic_sources_only": True, "synthetic_responses": responses}


with tempfile.TemporaryDirectory(prefix="friday-executive-trial-") as temporary:
    result = asyncio.run(trial(Path(temporary)))
target = Path(__file__).with_name("executive-live-probe.json")
target.write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result))
assert result["facts_created"] == 0 and result["source_task_cursor"] == 0 and result["source_task_steps"] == []
