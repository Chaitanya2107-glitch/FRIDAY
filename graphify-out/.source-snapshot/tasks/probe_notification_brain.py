"""Opt-in live provider probe using synthetic context only; never delivers a notice."""

import asyncio
import json
import logging
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def probe():
    from core.config import config

    with tempfile.TemporaryDirectory(prefix="friday-notification-probe-") as directory:
        root = Path(directory)
        config.MEMORY_DB_PATH = str(root / "reminders.db")
        config.MEMORY_DIR = root
        config.LOGS_DIR = root / "logs"
        config.NOTIFICATION_REVIEW_ENABLED = True
        from services.mind import reminder_review
        from services.mind.cognition import cognition
        from services.reminders.service import Reminder

        cognition.path = root / "cognition.db"
        now = datetime.now()
        context = {"date": now.date().isoformat(), "dated_facts": [], "remembered_facts": [],
                   "live": {"activity": "coding", "away": False, "speaking": False, "listening": False},
                   "busy": False, "telegram_eligible": False, "workspace": {}, "reasoning": {},
                   "recent_outcomes": []}

        async def synthetic_snapshot(*args):
            return json.loads(json.dumps(context))

        reminder_review._snapshot = synthetic_snapshot
        results = []

        async def check(label, text, expected):
            result = await reminder_review.review(Reminder(7, text, now.timestamp()), now)
            results.append({"scenario": label, "expected": expected, "actual": result.action,
                            "reason": result.reason, "evidence": list(result.evidence),
                            "matched": result.action == expected})

        await check("due_requested_reminder", "Drink water", "send")
        context["dated_facts"] = [{"id": "synthetic:1", "from": now.date().isoformat(),
            "through": now.date().isoformat(), "fact": "No classes today", "classes_available": False,
            "subject": "all regular classes"}]
        await check("cancelled_class", "Attend DBMS class", "suppress")
        context["dated_facts"] = []
        context["busy"] = True
        await check("busy_context", "Drink water", "defer")
        context["busy"] = False
        context["remembered_facts"] = [{"id": 9, "text": "The appointment with Ada today was cancelled.",
            "source": "told", "created_at": now.isoformat(), "happens_on": now.date().isoformat()}]
        await check("owner_cancelled_appointment", "Attend the appointment with Ada", "suppress")
        report = {"context": "Synthetic only; no notifications, speech, messages or owner state changes.",
                  "selected_provider": config.ACTIVE_PROVIDER, "results": results}
        target = Path(__file__).with_name("notification-brain-live-probe.json")
        target.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        from providers.ollama.runtime import runtime
        await runtime.close()
        logging.shutdown()  # Windows must release the temporary log before cleanup.


if __name__ == "__main__":
    asyncio.run(probe())
