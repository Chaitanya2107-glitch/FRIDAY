"""
services/memory/reading_list.py

A reading list in memory/reading_list.json:
  "add this to my reading list" / "save this for later" — the page you just had open in Chrome/Edge
  "add https://… to my reading list"
  "what's on my reading list", "open reading list 2", "done with reading list 2", "clear my reading list"

"This" is the most recently visited page in the browser's history (read directly: the activity log
keeps only domains). # ponytail: last visit ≈ the tab you're on; ask the browser for the active tab if it misfires
"""

import json
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from core.config import config
from services.activity.log import BROWSER_HISTORIES, _CHROME_EPOCH
from services.automation.system_control import AutomationError, system

READING_ACTIONS = {"add_reading", "list_reading", "open_reading", "done_reading", "clear_reading"}
path = config.MEMORY_DIR / "reading_list.json"  # tests point this elsewhere
RECENT_MINUTES = 30
URL = re.compile(r"https?://\S+", re.I)

_LIST_NAME = r"(?:my |the )?reading list"
_ADD = re.compile(rf"^(?:add|save|put) (?P<what>.+?) (?:to|on|in) {_LIST_NAME}$|^(?:save|keep) (?P<this>this|that|it|this page)"
                  r" (?:for later|to read later)$|^read (?:this|it) later$", re.I)
_LIST = re.compile(rf"^(?:(?:what's|what is) on|(?:show|read|list|open)(?: me)?) {_LIST_NAME}$|^my reading list$", re.I)
_OPEN = re.compile(rf"^open (?:item |number )?(?P<n>\d+) (?:from|on|in) {_LIST_NAME}$|^open {_LIST_NAME} (?:item |number )?(?P<m>\d+)$", re.I)
_DONE = re.compile(rf"^(?:done with|finished|remove|delete|cross off) (?:item |number )?(?P<n>\d+) (?:from|on) {_LIST_NAME}$"
                   rf"|^(?:done with|finished|remove|delete|cross off) {_LIST_NAME} (?:item |number )?(?P<m>\d+)$", re.I)
_CLEAR = re.compile(rf"^(?:clear|empty|delete) {_LIST_NAME}$", re.I)
_THIS = {"this", "that", "it", "this page", "this article", "this video", "the page", "this site"}


def match_reading_command(text: str, original: str = "") -> dict | None:
    """`text` is normalized; `original` keeps a URL's letter case."""
    text = text.strip().rstrip(".!?")
    if _LIST.match(text):
        return {"type": "system", "action": "list_reading"}
    if _CLEAR.match(text):
        return {"type": "system", "action": "clear_reading"}
    if m := _OPEN.match(text):
        return {"type": "system", "action": "open_reading", "number": int(m["n"] or m["m"])}
    if m := _DONE.match(text):
        return {"type": "system", "action": "done_reading", "number": int(m["n"] or m["m"])}
    if m := _ADD.match(text):
        what = (m["what"] or "this").strip()
        url = URL.search(original or text)
        return {"type": "system", "action": "add_reading", "url": url[0].rstrip(".,)") if url else None,
                "title": None if url or what.lower() in _THIS else what}
    return None


def load() -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(items: list[dict]) -> None:
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def last_page(now: datetime | None = None) -> tuple[str, str] | None:
    """(url, title) of the most recent visit in Chrome/Edge within RECENT_MINUTES, or None."""
    since = (now or datetime.now()) - timedelta(minutes=RECENT_MINUTES)
    cursor = int((since.astimezone() - _CHROME_EPOCH).total_seconds() * 1_000_000)
    best = None
    for history in BROWSER_HISTORIES:
        if not history.exists():
            continue
        with tempfile.TemporaryDirectory() as tmp:  # the browser keeps the live file locked
            copy = Path(tmp) / "History"
            shutil.copy2(history, copy)
            with closing(sqlite3.connect(copy)) as conn:
                row = conn.execute("SELECT url, title, last_visit_time FROM urls WHERE last_visit_time > ? "
                                   "ORDER BY last_visit_time DESC LIMIT 1", (cursor,)).fetchone()
        if row and (best is None or row[2] > best[2]):
            best = row
    return (best[0], best[1] or best[0]) if best else None


def add(url: str | None, title: str | None) -> str:
    if not url and not title:
        found = last_page()
        if not found:
            raise AutomationError("I couldn't find a page you had open in Chrome or Edge in the last half hour.")
        url, title = found
    items = load()
    if url and any(i.get("url") == url for i in items):
        return "That's already on your reading list."
    items.append({"title": title or url, "url": url, "added": datetime.now().isoformat(timespec="seconds")})
    _save(items)
    return f"Added to your reading list: {title or url}. ({len(items)} on it.)"


def _item(number: int) -> tuple[list[dict], dict]:
    items = load()
    if not 1 <= number <= len(items):
        raise AutomationError(f"There's no item {number} on your reading list." + (f" It has {len(items)}." if items else ""))
    return items, items[number - 1]


def run(parsed: dict) -> str:
    action = parsed["action"]
    if action == "add_reading":
        return add(parsed.get("url"), parsed.get("title"))
    if action == "list_reading":
        items = load()
        return "Your reading list:\n" + "\n".join(f"{n}. {i['title']}" for n, i in enumerate(items, 1)) if items \
            else "Your reading list is empty."
    if action == "clear_reading":
        count = len(load())
        _save([])
        return f"Cleared {count} item{'s' if count != 1 else ''} from your reading list." if count else "Your reading list is already empty."
    items, item = _item(int(parsed["number"]))
    if action == "open_reading":
        if item.get("url"):
            return system.open_url(item["url"])
        return system.search_chrome(item["title"])
    items.remove(item)
    _save(items)
    return f"Crossed off: {item['title']}."
