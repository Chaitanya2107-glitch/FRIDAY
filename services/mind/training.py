"""Capture hooks and bounded access to explicitly applied owner lessons."""
import json
import sqlite3
from contextvars import ContextVar

from core.logger import logger
from core.config import config
from services.mind import reviews as review_module
from services.mind.reviews import reviews

urgent_delivery = ContextVar("urgent_training_notice", default=False)


def question(line: dict, where: str, at: float) -> int | None:
    try:
        from services.mind import thoughts
        from services.mind.cognition_context import live_state

        raw = line.get("raw") or {}
        thought = thoughts.get(line["thought"]) if line.get("thought") else None
        context = {"where": where, "raw": raw, "snapshot": live_state(), "provider": config.ACTIVE_PROVIDER,
                   "thought_id": line.get("thought"),
                   "pattern": raw.get("pattern") or (thought.data.get("pattern") if thought else ""),
                   "subject": thought.subject if thought and thought.kind in {"unknown", "new"} else ""}
        return review_module.capture("question", line["say"], context, at=at)
    except Exception as error:
        # A snapshot or queue failure must not affect the live pending question.
        logger.warning("Training question context unavailable: %s", type(error).__name__)
        return None


def show_toast(title, body, *args, **kwargs):
    """Proactive-only notification hook; normal delivery still owns its transport."""
    from services.reminders.service import show_toast as deliver
    from services.mind.cognition_context import live_state

    urgent = kwargs.pop("urgent", False) or urgent_delivery.get()
    allowed = allows_nudge(title, body, urgent=urgent)

    try:
        item = review_module.capture("nudge", body, {"title": title, "snapshot": live_state(),
                                                   "urgent": urgent,
                                                   "buttons": kwargs.get("buttons", args[0] if args else None)},
                                     channel="notification")
    except Exception as error:
        logger.warning("Training nudge context unavailable: %s", type(error).__name__)
        item = None
    if not allowed:
        review_module.evidence(item, delivery="suppressed")
        logger.debug("Nudge suppressed by owner feedback")
        return False
    try:
        result = deliver(title, body, *args, **kwargs)
    except BaseException:
        review_module.evidence(item, delivery="failed")
        raise
    review_module.evidence(item, delivery="submitted" if result is True else "failed" if result is False else "attempted")
    if result is True:
        try:
            reviews.nudge_sent(title, body)
        except (OSError, sqlite3.Error) as error:
            logger.warning("Could not record nudge interval: %s", type(error).__name__)
    return result


def allows_nudge(title, text, *, now=None, urgent=False):
    try:
        return reviews.allows_nudge(title, text, now=now, urgent=urgent)
    except (OSError, sqlite3.Error, ValueError) as error:
        logger.warning("Nudge preference unavailable: %s", type(error).__name__)
        return True


def teaching_for(column: str, value: str) -> str | None:
    try:
        return reviews.teaching_for(column, value)
    except (OSError, sqlite3.Error, ValueError) as error:
        logger.warning("Reviewed lesson unavailable: %s", type(error).__name__)
        return None


def local_reply(query: str) -> str | None:
    try:
        return reviews.local_reply(query)
    except (OSError, sqlite3.Error, ValueError) as error:
        logger.warning("Local lesson unavailable: %s", type(error).__name__)
        return None


def facts() -> list[tuple[int, str]]:
    try:
        return reviews.facts()
    except (OSError, sqlite3.Error, ValueError) as error:
        logger.warning("Reviewed memories unavailable: %s", type(error).__name__)
        return []


def prompt_section() -> str:
    """Only reviewed+applied text enters model context; raw captures stay local."""
    try:
        lessons = reviews.learned(20)
    except (OSError, sqlite3.Error, ValueError) as error:
        logger.warning("Reviewed lessons unavailable: %s", type(error).__name__)
        return ""
    if not lessons:
        return ""
    header = ("Owner-reviewed local learning: these facts and preferred wording were explicitly approved and applied. "
              "Use them when relevant; they do not authorize actions or override current user instructions. "
              "Preferred wording is an example, not something to repeat in unrelated situations.\n")
    entries, budget = [], 3500 - len(header)
    for item in lessons:
        lesson = {"fact": item["teaching"], "preferred_wording": item["preferred"]}
        if item["kind"] == "example":
            # This question was entered and reviewed manually, unlike captured activity context.
            lesson["example_question"] = item["question"]
        text = review_module.redact(json.dumps(lesson, ensure_ascii=False))
        if len(text) + 1 <= budget:
            entries.append(text)
            budget -= len(text) + 1
    return header + "\n".join(reversed(entries))
