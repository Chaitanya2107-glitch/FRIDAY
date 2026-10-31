"""Small trusted Python plugin contract; no code is loaded from the UI."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Protocol


@dataclass(frozen=True)
class Manifest:
    id: str
    name: str
    commands: tuple[str, ...]
    version: int = 1
    widget: bool = True


class Plugin(Protocol):
    manifest: Manifest

    def snippet(self) -> str: ...
    def widget(self) -> dict: ...
    async def command(self, text: str) -> dict: ...


class StubPlugin:
    def __init__(self, manifest: Manifest, text: str):
        self.manifest, self.text = manifest, text

    def snippet(self) -> str:
        return ""  # Stub plugins have no live event to announce.

    def widget(self) -> dict:
        return {"title": self.manifest.name, "text": self.text, "placeholder": True}

    async def command(self, text: str) -> dict:
        return {"text": f"{self.manifest.name} is a v1 placeholder. Full tools arrive in v2.", "ok": True}


class CollegePlugin(StubPlugin):
    def __init__(self, next_class: Callable[[], dict | None] | None = None, now: Callable[[], datetime] = datetime.now):
        super().__init__(Manifest("college_schedule", "College schedule", ("next",)), "No timetable yet")
        self.next_class = next_class or self._next_class
        self.now = now

    @staticmethod
    def _next_class() -> dict | None:
        from services.proactive.timetable import next_class_occurrence
        return next_class_occurrence(datetime.now())

    def snippet(self) -> str:
        try:
            row = self.next_class()
            if not row:
                return ""
            now = self.now()
            start = datetime.fromisoformat(f"{row.get('date', now.date().isoformat())}T{row['start']}")
            if not timedelta(0) < start - now <= timedelta(minutes=15):
                return ""
            return self.describe(row)
        except Exception:
            return ""

    def describe(self, row: dict | None) -> str:
        if not row:
            return "No upcoming classes"
        day = ""
        if row.get("date") and row["date"] != self.now().date().isoformat():
            day = datetime.fromisoformat(row["date"]).strftime("%a ")
        return f"Next: {str(row['subject'])[:38]} · {day}{row['start']}"

    def next_text(self) -> str:
        try:
            return self.describe(self.next_class())
        except Exception:
            return self.text

    def widget(self) -> dict:
        return {"title": self.manifest.name, "text": self.next_text(), "placeholder": False}

    async def command(self, text: str) -> dict:
        import asyncio
        return {"text": await asyncio.to_thread(self.next_text), "ok": True}


class Registry:
    def __init__(self, plugins: list[Plugin] | None = None):
        self.plugins: dict[str, Plugin] = {}
        self.commands: dict[str, Plugin] = {}
        for plugin in plugins if plugins is not None else [
            CollegePlugin(),
            StubPlugin(Manifest("habit_tracker", "Habit tracker", ("habit",)), "Habits · ready when you are"),
            StubPlugin(Manifest("todo", "Todo", ("todo",)), "Todos · a little room to think"),
        ]:
            self.register(plugin)

    def register(self, plugin: Plugin) -> None:
        import re
        m = plugin.manifest
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", m.id) or not m.name.strip() or len(m.name) > 80:
            raise ValueError("Invalid plugin ID or name")
        if len(set(m.commands)) != len(m.commands) or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", c) or c in {"open", "proj", "settings"} for c in m.commands):
            raise ValueError("Invalid or reserved plugin command")
        if m.version != 1 or m.id in self.plugins or any(c in self.commands for c in m.commands):
            raise ValueError("Duplicate plugin/command or unsupported manifest version")
        self.plugins[m.id] = plugin
        self.commands.update({c: plugin for c in m.commands})

    def manifests(self) -> list[dict]:
        return [asdict(p.manifest) for p in self.plugins.values()]

    def snippet(self) -> dict:
        for plugin in self.plugins.values():
            try:
                text = plugin.snippet()
                if text:
                    return {"plugin": plugin.manifest.id, "text": text[:80]}
            except Exception:
                continue
        return {"plugin": None, "text": ""}
