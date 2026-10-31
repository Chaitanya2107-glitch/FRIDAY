"""Parse commands into text or allowlisted ID actions. Never spawn a process."""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Awaitable, Callable

from .config import IslandConfig
from .plugins import Registry


def score(query: str, name: str) -> float:
    query, name = query.casefold().strip(), name.casefold()
    if not query:
        return 0.5
    if name == query:
        return 4.0
    if name.startswith(query):
        return 3.0
    if query in name:
        return 2.0
    positions = iter(name)
    subsequence = all(any(c == candidate for candidate in positions) for c in query)
    return max(1.0 if subsequence else 0, SequenceMatcher(None, query, name).ratio())


async def friday_answer(text: str) -> str:
    # Do not use /chat: its automation router bypasses the Island's launch policy.
    from core.config import config
    from services.mind.language import answer
    result = await answer(text, config.ACTIVE_PROVIDER, [], 500)
    return result.content


class Engine:
    def __init__(self, registry: Registry, assistant: Callable[[str], Awaitable[str]] = friday_answer):
        self.registry, self.assistant = registry, assistant

    def suggestions(self, text: str, config: IslandConfig) -> list[dict]:
        parts = text.strip().split(maxsplit=1)
        head, tail = (parts[0], parts[1] if len(parts) > 1 else '') if parts else ('', '')
        candidates: list[tuple[str, str]] = []
        plugin = self.registry.commands.get(head.casefold())
        if plugin and hasattr(plugin, 'suggestions'):
            return plugin.suggestions(text)
        if head.casefold() == "open":
            return []  # Installed apps and favourites are indexed natively.
        if head == "proj":
            items = config.projects
            candidates = [(f"{head} {p.name}", p.name) for p in items]
            query = tail
        else:
            candidates = [(c, c) for c in ["settings", "proj", "open", *self.registry.commands, "note", "focus"]]
            query = text
        ranked = sorted(candidates, key=lambda row: score(query, row[1]), reverse=True)
        return [{"text": label, "detail": "Configured app" if head == "open" else "Command"}
                for label, name in ranked if score(query, name) >= 0.5][:6]

    async def execute(self, text: str, config: IslandConfig) -> dict:
        text = text.strip()
        if not text or len(text) > 4000 or "\x00" in text:
            return {"text": "Enter a command (up to 4000 characters).", "ok": False}
        parts = text.split(maxsplit=1)
        head, tail = parts[0], parts[1] if len(parts) > 1 else ''
        head = head.casefold()
        if head == "settings":
            return {"text": "Settings", "ok": True, "action": {"kind": "settings"}}
        if head == "open":
            return {"text": "Search installed apps", "ok": True,
                    "action": {"kind": "app_search", "query": tail.strip()}}
        if head == "proj":
            items = config.projects
            if not tail.strip():
                return {"text": "Choose a project.", "ok": False}
            ranked = sorted(items, key=lambda p: score(tail, p.name), reverse=True)
            if not ranked or score(tail, ranked[0].name) < 0.5:
                return {"text": "No project found. Add it in Settings.", "ok": False}
            best = ranked[0]
            if len(ranked) > 1 and score(tail, best.name) == score(tail, ranked[1].name):
                return {"text": "More than one match. Use a longer name.", "ok": False}
            return {"text": f"Opening {best.name}", "ok": True,
                    "action": {"kind": "project", "id": best.id}}
        if head in self.registry.commands:
            return await self.registry.commands[head].command(text)
        return {"text": await self.assistant(text), "ok": True}
