"""Explicit local controls and private inspection; screen content never becomes an action."""
from contextvars import ContextVar

from services.automation.results import ActionResult
from services.screen_watch import service

PRIVATE_MEMORY = "Private local screen-awareness response."
local_request = ContextVar("local_screen_request", default=True)
CONTROLS = {
    "start screen awareness": "start", "start watching my screen": "start", "watch my screen": "start",
    "turn on screen awareness": "start", "enable screen awareness": "start",
    "resume screen awareness": "resume", "resume watching my screen": "resume",
    "pause screen awareness": "pause", "pause watching my screen": "pause",
    "stop watching my screen": "stop", "stop screen awareness": "stop",
    "turn off screen awareness": "stop", "disable screen awareness": "stop",
}
QUERIES = {"what am i doing", "what am i doing right now", "what am i reading", "what am i looking at",
           "what can you see", "what do you see", "what's on my screen", "what is on my screen"}
HISTORY = {"screen memory", "screen history", "what have you noticed on my screen"}
FORGET = {"forget screen memory", "clear screen memory", "forget what you saw"}


def normalized(text):
    return " ".join(text.lower().replace("\u2019", "'").strip().rstrip(".!?").split())


def is_query(text):
    return normalized(text) in QUERIES


def match(text):
    normal = normalized(text)
    if normal in CONTROLS:
        return CONTROLS[normal]
    if normal in {"screen awareness status", "screen watching status"}:
        return "status"
    if normal in HISTORY:
        return "history"
    if normal in FORGET:
        return "forget"
    if normal in QUERIES and service.watch.store.settings()["enabled"]:
        return "current"
    return None


def _result(text, success=True):
    return ActionResult(success, text, PRIVATE_MEMORY, False)


async def handle(text, *, remote=False):
    action = match(text)
    if action is None:
        return None
    if remote or not local_request.get():
        return _result("Screen awareness and its memories are available at the laptop only.", False)
    from services.automation import intent
    from services.mind import talk, conversation_context
    from services.computer.agent import computer_agent
    from services.browser.service import automation
    intent.cancel_pending_confirmation()
    talk.retire_question()
    conversation_context.retire_dialogue()
    computer_agent.cancel()
    automation.abandon_pending()
    watch = service.watch
    if action in {"start", "resume", "pause", "stop"}:
        watch.control(action)
        return _result({
            "start": "Screen awareness is enabled. I'll read the active window once the watching badge is visible. All analysis stays local.",
            "resume": "Screen awareness is resumed. The visible watching badge must be present before I read anything.",
            "pause": "Screen awareness is paused.",
            "stop": "Screen awareness is off.",
        }[action])
    if action == "forget":
        count = watch.store.forget()
        watch.control("pause")
        return _result(f"I deleted {count} screen summaries and paused screen awareness.")
    if action == "status":
        state = watch.status()
        return _result("Screen awareness: " + state["state"].replace("_", " ") + ". Analysis is local; raw screenshots and app text aren't saved.")
    if action == "history":
        rows = watch.store.history()
        return _result("No screen summaries are saved." if not rows else
                       "Provisional screen interpretations, not confirmed tasks:\n" + "\n".join(
                           f'{r["at"]}: {r["summary"]} Activity guess: {r["activity"] or "unknown"}.'
                           for r in rows))
    row = await watch.current()
    if row:
        return _result(f'Last screen check at {row["at"]}: {row["summary"]}\n'
                       f'My activity interpretation: {row["activity"] or "unknown"}. '
                       "This is a model interpretation; your exact intent and progress aren't verified.")
    state = watch.status()["state"].replace("_", " ")
    return _result(f"Screen awareness is {state}. I don't have a safe, recent screen interpretation for this window yet.")
