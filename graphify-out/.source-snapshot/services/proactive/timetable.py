"""
services/proactive/timetable.py

The user's weekly class timetable.

  "read my timetable from the screen"         → the vision AI reads the timetable on screen, once
  "read my timetable from timetable.png"      → …or from an image / PDF file (found with Everything)
  "what classes do I have today / tomorrow / on Monday", "what's my next class"
  "add class DBMS on Monday 10 to 11 in room 204", "remove class DBMS on Monday", "clear my timetable"
  "my subjects are finance, management and marketing", "add subject OS", "what are my subjects"
     (extra subjects in memory/subjects.json, for filing downloads and deadlines; the timetable's count too)

Kept in memory/timetable.json (editable by hand). Today's classes are in the
morning briefing, and WARN_MINUTES before each class a notification (spoken
too, unless it's quiet hours or the user is gaming / fullscreen) says what's
next and where — from services/proactive/watcher.py.
"""

import asyncio
import io
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from core.config import config
from core.logger import logger
from services.automation.system_control import AutomationError
from services import settings_store
from services.proactive import deadline_store
from services.proactive.timetable_extract import extract_classes, parse_classes
from services.college.reading import room_for, warning_room

path = config.MEMORY_DIR / "timetable.json"  # tests point this elsewhere
subjects_path = config.MEMORY_DIR / "subjects.json"
WARN_MINUTES = 10
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
TIMETABLE_ACTIONS = {"show_classes", "next_class", "add_class", "remove_class", "clear_timetable",
                     "set_subjects", "add_subject", "list_subjects"}  # import is async
MAX_IMAGE_SIDE = 2000
READ_PROMPT = (
    "This is a weekly class timetable. {which}Reply with JSON only, no other text — a list of objects "
    '{{"day": "monday"…"sunday", "start": "HH:MM" (24-hour), "end": "HH:MM", "subject": "short name", '
    '"room": "room or null"}}. Skip breaks and lunch. If a class repeats on several days, list each day. '
    "Read the times from the timetable's own time row/column."
)
ALL_CLASSES = "List every class in it. "
ONE_SECTION = ("It may cover several sections or classes: list ONLY the classes of section {section} "
               "and ignore every other section. ")
MAX_REPLY_TOKENS = 8000  # a week of classes, plus room for models that think before answering
MAX_PDF_PAGES = 3

_DAY = rf"(?:{'|'.join(DAYS)})"
_TIME = r"\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?"
_IMPORT = re.compile(
    r"^(?:read|import|load|get|scan|set up|save|learn)\s+(?:my\s+|the\s+)?(?:class\s+)?(?:time\s?table|class schedule)"
    r"\s+(?:from|off|in)\s+(?P<source>.+?)(?:\s+for\s+(?:section\s+|my section\s+)?(?P<section>[\w-]+))?$", re.I,
)
_THIS = re.compile(  # "this is my timetable" = the one on screen
    r"^(?:this|here)(?: is|'s) (?:my |the )?(?:new |class )?(?:time\s?table|class schedule)"
    r"(?:\s+for\s+(?:section\s+|my section\s+)?(?P<section>[\w-]+))?$", re.I,
)
_SHOW = re.compile(
    rf"^(?:(?:what|which) classes (?:do i have|have i got|are there)|(?:show|tell)(?: me)? my (?:classes|time\s?table)"
    rf"|(?:what(?:'s| is) )?my (?:time\s?table|classes|class schedule)|classes)(?:\s+(?:for |on )?(?P<day>today|tomorrow|{_DAY}))?$",
    re.I,
)
_NEXT = re.compile(r"^(?:what(?:'s| is)\s+)?(?:my\s+)?next (?:class|lecture)$|^when(?:'s| is) my next (?:class|lecture)$", re.I)
_ADD = re.compile(
    rf"^add (?:a )?class (?P<subject>.+?) (?:on |every )?(?P<day>{_DAY}) (?:from |at )?(?P<start>{_TIME})"
    rf"\s*(?:to|-|till|until)\s*(?P<end>{_TIME})(?: in (?:room )?(?P<room>.+))?$", re.I,
)
_REMOVE = re.compile(rf"^(?:remove|delete|cancel) (?:the )?class (?P<subject>.+?)(?: on (?P<day>{_DAY}))?$", re.I)
_CLEAR = re.compile(r"^(?:clear|delete|reset|forget) (?:my |the )?(?:time\s?table|class schedule)$", re.I)
_SET_SUBJECTS = re.compile(r"^my subjects are:?\s+(?P<list>.+)$", re.I)
_ADD_SUBJECT = re.compile(r"^add (?:a )?subject:?\s+(?P<name>.+)$", re.I)
_LIST_SUBJECTS = re.compile(r"^(?:what are|list|show)(?: me)? (?:all )?my subjects$|^my subjects$", re.I)
# Looser questions: "whats on my timetable tom", "do i have class today", "don't u have my timetable"
_ASK_START = re.compile(r"^(?:what|what's|whats|wat|which|when|do|does|don't|dont|any|is|are|have|got|show|tell|"
                        r"u|you|can|could|check)\b", re.I)
_ASK_ABOUT = re.compile(r"\b(?:time\s?table|class schedule)\b"
                        r"|\b(?:any|i have|i got|is there|are there)\s+(?:a\s+|any\s+)?(?:class|classes|lectures?)\b"
                        r"|\bmy\s+(?:\w+\s+)?(?:classes|lectures)\b|\b(?:first|last|next)\s+(?:class|lecture)\b", re.I)
_NOT_ASK = re.compile(r"\b(?:file|sent|send|screen|photo|picture|pic|image|pdf|screenshot|add|remove|delete|clear|"
                      r"change|update|import|read|scan|why|how)\b", re.I)
_ASK_DAY = re.compile(rf"\b(?P<day>today|tonight|tomorrow|tmrw|tmr|tom|{_DAY})\b", re.I)
_DAY_SHORT = {"tonight": "today", "tmrw": "tomorrow", "tmr": "tomorrow", "tom": "tomorrow"}

_warned: set[str] = set()  # classes already warned about today


# ── The file ──────────────────────────────────────────────────────────────────

def load() -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise AutomationError(f"I couldn't read {path} — is there a typo in it? ({e})") from e
    return sorted((c for c in data if isinstance(c, dict)), key=lambda c: (DAYS.index(c["day"]), c["start"]))


def _save(classes: list[dict]) -> None:
    classes = sorted(classes, key=lambda c: (DAYS.index(c["day"]), c["start"]))
    settings_store.save(path, classes)


def edit():
    return deadline_store.edit(path)


def parse_time(text: str) -> str:
    """ "10", "10:30", "2 pm", "14:00" → "HH:MM". Without am/pm, 1–7 means afternoon (classes aren't at 3 am)."""
    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", text.strip().lower())
    if not m:
        raise AutomationError(f"I don't understand the time {text!r}.")
    hour, minute, half = int(m[1]), int(m[2] or 0), (m[3] or "").replace(".", "")
    if half == "pm" and hour < 12:
        hour += 12
    elif half == "am" and hour == 12:
        hour = 0
    elif not half and 1 <= hour <= 7:
        hour += 12
    if hour > 23 or minute > 59:
        raise AutomationError(f"I don't understand the time {text!r}.")
    return f"{hour:02d}:{minute:02d}"


def _clean(entry: dict) -> dict | None:
    """One class from the AI's JSON, checked; None if it isn't usable."""
    try:
        day = str(entry["day"]).strip().lower()[:3]
        day = next(d for d in DAYS if d.startswith(day))
        start, end = parse_time(str(entry["start"])), parse_time(str(entry["end"]))
        subject = str(entry["subject"]).strip()
    except (KeyError, StopIteration, AutomationError, TypeError):
        return None
    room = entry.get("room")
    return {"day": day, "start": start, "end": end, "subject": subject,
            "room": str(room).strip() if room not in (None, "", "null") else None} if subject else None


# ── Describing ────────────────────────────────────────────────────────────────

def _clock(hhmm: str) -> str:
    return datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0").lower()


def _describe(c: dict, with_day: bool = False, *, metadata: bool = True) -> str:
    saved_room = room_for(c) if metadata else c.get('room')
    room = f' in {saved_room}' if saved_room else ''
    return f"{c['day'].title() + ' ' if with_day else ''}{_clock(c['start'])} {c['subject']}{room}"


def classes_on(day: str) -> list[dict]:
    return [c for c in load() if c["day"] == day]


def classes_for_date(day: date) -> list[dict]:
    from services.memory import schedule
    from services.proactive import class_sessions
    known = schedule.facts()
    return class_sessions.effective(day, [c for c in classes_on(DAYS[day.weekday()])
                                         if schedule.allowed(day, c["subject"], known)])


def today_line(now: datetime) -> str:
    """For the morning briefing ("" without a timetable)."""
    if not load():
        return ""
    today = classes_for_date(now.date())
    if not today:
        return "No classes today."
    return f"Classes today: {', '.join(_describe(c) for c in today)}."


def next_class_occurrence(now: datetime) -> dict | None:
    """Shared selection for next-class prose and native overview; copies only."""
    classes = load()
    if not classes:
        raise AutomationError('I don\'t have your timetable yet. Open it and say "read my timetable from the screen".')
    from services.memory import schedule
    from services.proactive import class_sessions
    known = schedule.facts()
    changes = class_sessions.load()
    for days_ahead in range(368):  # dated exceptions can span longer than one timetable week
        day = DAYS[(now.weekday() + days_ahead) % 7]
        target = (now + timedelta(days=days_ahead)).date()
        for c in class_sessions.effective(target, [c for c in classes if c["day"] == day and
                  schedule.allowed(target, c["subject"], known)], changes):
            if days_ahead or c["start"] > now.strftime("%H:%M"):
                return {**c, 'date': target.isoformat()}
    return None


def next_class(now: datetime) -> str:
    c = next_class_occurrence(now)
    if c:
        saved_room = room_for(c)
        days_ahead = (date.fromisoformat(c['date']) - now.date()).days
        when = 'today' if days_ahead == 0 else 'tomorrow' if days_ahead == 1 else f"on {c['day'].title()}"
        return f"Your next class is {c['subject']} {when} at {_clock(c['start'])}" + \
            (f' in {saved_room}.' if saved_room else '.')
    return "You don't have any classes coming up."


def due_warnings(now: datetime) -> list[str]:
    """Classes starting within WARN_MINUTES that haven't been warned about yet (once each)."""
    try:
        today = classes_for_date(now.date())
    except AutomationError:
        return []
    warnings = []
    for c in today:
        start = now.replace(hour=int(c["start"][:2]), minute=int(c["start"][3:]), second=0, microsecond=0)
        key = f"{now.date()}:{c['start']}:{c['subject']}"
        if timedelta(0) < start - now <= timedelta(minutes=WARN_MINUTES) and key not in _warned:
            _warned.add(key)
            minutes = max(1, round((start - now).total_seconds() / 60))
            saved_room = warning_room(c)
            room = f' in {saved_room}' if saved_room else ''
            from services.proactive.deadlines import for_subject  # avoid an import cycle

            warnings.append(f"{c['subject']} starts in {minutes} minute{'s' if minutes != 1 else ''}{room}."
                            + for_subject(c["subject"], now))
    return warnings


# ── Subjects ──────────────────────────────────────────────────────────────────

SMALL_WORDS = ("and", "of", "the", "with", "for", "in", "to")  # left out of initials


def _extra_subjects() -> list[str]:
    """The subjects the user named ("my subjects are …", memory/subjects.json)."""
    try:
        extra = json.loads(subjects_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in extra if isinstance(e, str)]


def _initials(name: str) -> str:
    """ "Database Management Systems" → "dbms"; "" for a one-word name."""
    words = re.findall(r"[a-z0-9]+", name.lower())
    return "".join(w[0] for w in words if w not in SMALL_WORDS) if len(words) > 1 else ""


def abbreviates(short: str, full: str) -> bool:
    """Whether `short` abbreviates the multi-word `full`: each word's first letter in order, plus maybe letters
    from inside a word — "DS" Data Structures, "DBMS" DataBase Management Systems, "EVS" EnVironmental Science."""
    words = [w for w in re.findall(r"[a-z0-9]+", full.lower()) if w not in SMALL_WORDS]
    short = short.lower()
    if len(words) < 2 or not short.isalnum():
        return False

    def fits(i: int, w: int) -> bool:  # short[i:] from words[w:]
        if w == len(words):
            return i == len(short)
        if i >= len(short) or short[i] != words[w][0]:
            return False
        i, inside, pos = i + 1, words[w][1:], 0
        while not fits(i, w + 1):  # take one more letter from inside this word, and try again
            if i >= len(short) or (pos := inside.find(short[i], pos)) < 0:
                return False
            i, pos = i + 1, pos + 1
        return True

    return fits(0, 0)


def subjects() -> list[str]:
    """The timetable's subjects and the ones the user named, each once. A named one that a timetable subject
    abbreviates ("Data Structures" for DS) is that subject's full name, not another subject."""
    try:
        listed = [c["subject"] for c in load()]
    except AutomationError:
        listed = []
    seen: dict[str, str] = {}
    for name in listed + [e for e in _extra_subjects() if not any(abbreviates(s, e) for s in listed)]:
        seen.setdefault(name.lower(), name)
    return list(seen.values())


def aliases(subject: str) -> list[str]:
    """The subject and the full names the user gave it: "DS" → ["DS", "Data Structures"]."""
    return [subject] + [e for e in _extra_subjects() if abbreviates(subject, e)]


def _save_subjects(names: list[str]) -> None:
    settings_store.save(subjects_path, names)


def mentions(text: str, subject: str) -> bool:
    """Whether text names the subject, or its initials for a multi-word one ("Discrete Mathematics and Graph Theory" → DMGT)."""
    words = re.findall(r"[a-z0-9]+", subject.lower())
    names = [" ".join(words), _initials(subject)]
    flat = " ".join(re.findall(r"[a-z0-9]+", text.lower()))
    return any(name and re.search(rf"\b{re.escape(name)}\b", flat) for name in names)


def mentions_subject(text: str, forms: list[str]) -> bool:
    """Whether text names any form of a subject (from aliases())."""
    return any(mentions(text, form) for form in forms)


def subject_named(said: str) -> str:
    """The user's subject that `said` names ("data structures" / "d b m s" → "DS" / "DBMS"), else `said` as given."""
    said = re.sub(r"\b(\w) (?=\w\b)", r"\1", said.strip(" .?"))  # "d b m s" (speech) → "dbms"
    return next((s for s in subjects() if any(mentions(said, f) or mentions(f, said) for f in aliases(s))), said)


# ── Commands ──────────────────────────────────────────────────────────────────

def match_timetable_command(text: str) -> dict | None:
    """Timetable commands. `text` has been through normalize_command()."""
    text = text.strip()
    if m := _IMPORT.match(text):
        return {"type": "system", "action": "import_timetable", "source": m["source"].strip(" ."),
                "section": (m["section"] or "").upper()}
    if m := _THIS.match(text):
        return {"type": "system", "action": "import_timetable", "source": "screen",
                "section": (m["section"] or "").upper()}
    if _NEXT.match(text):
        return {"type": "system", "action": "next_class"}
    if m := _SHOW.match(text):
        return {"type": "system", "action": "show_classes", "day": (m["day"] or "today").lower()}
    if m := _ADD.match(text):
        return {"type": "system", "action": "add_class", "subject": m["subject"].strip(), "day": m["day"].lower(),
                "start": m["start"], "end": m["end"], "room": (m["room"] or "").strip() or None}
    if m := _REMOVE.match(text):
        return {"type": "system", "action": "remove_class", "subject": m["subject"].strip(),
                "day": (m["day"] or "").lower()}
    if _CLEAR.match(text):
        return {"type": "system", "action": "clear_timetable"}
    if m := _SET_SUBJECTS.match(text):
        names = [n.strip(" .") for n in re.split(r",|\band\b|&", m["list"]) if n.strip(" .")]
        return {"type": "system", "action": "set_subjects", "names": names}
    if m := _ADD_SUBJECT.match(text):
        return {"type": "system", "action": "add_subject", "name": m["name"].strip(" .")}
    if _LIST_SUBJECTS.match(text):
        return {"type": "system", "action": "list_subjects"}
    if _ASK_START.match(text) and _ASK_ABOUT.search(text) and not _NOT_ASK.search(text):
        if re.search(r"\bnext\b", text, re.I):
            return {"type": "system", "action": "next_class"}
        day = (m["day"].lower() if (m := _ASK_DAY.search(text)) else "today")
        return {"type": "system", "action": "show_classes", "day": _DAY_SHORT.get(day, day)}
    return None


def prompt_line(now: datetime | None = None) -> str:
    """For the chat prompt, so the AI knows the timetable exists: today's and tomorrow's classes. "" without one."""
    now = now or datetime.now()
    try:
        if not load():
            return ""
        today, tomorrow = (classes_for_date((now + timedelta(days=i)).date()) for i in (0, 1))
    except AutomationError:
        return ""
    def day(found: list[dict]) -> str:
        return ", ".join(_describe(c) for c in found) or "no classes"
    return (f"The user's class timetable is saved (memory/timetable.json). Today: {day(today)}. "
            f"Tomorrow: {day(tomorrow)}. They can ask \"what classes do I have on <day>\" for other days.")


def run(parsed: dict, now: datetime | None = None) -> str:
    if parsed['action'] in {'add_class', 'remove_class', 'clear_timetable'}:
        with edit():
            return _run(parsed, now)
    if parsed['action'] in {'set_subjects', 'add_subject'}:
        with deadline_store.edit(subjects_path):
            return _run(parsed, now)
    return _run(parsed, now)


def _run(parsed: dict, now: datetime | None = None) -> str:
    now = now or datetime.now()
    action = parsed["action"]
    if action == "next_class":
        return next_class(now)
    if action == "set_subjects":
        _save_subjects(parsed["names"])
        return f"Got it: {', '.join(parsed['names'])}."
    if action == "add_subject":
        names = json.loads(subjects_path.read_text(encoding="utf-8")) if subjects_path.exists() else []
        _save_subjects(names + [parsed["name"]])
        return f"Added {parsed['name']} to your subjects."
    if action == "list_subjects":
        names = subjects()
        return f"Your subjects: {', '.join(names)}." if names else "I don't know your subjects yet. Say \"my subjects are …\"."
    classes = load()
    if action == "show_classes":
        if not classes:
            return 'I don\'t have your timetable yet. Open it and say "read my timetable from the screen".'
        day = parsed["day"]
        label = day
        if day in ("today", "tomorrow"):
            day = DAYS[(now.weekday() + (day == "tomorrow")) % 7]
        else:
            label = f"on {day.title()}"
        target = now.date() + timedelta(days=(DAYS.index(day) - now.weekday()) % 7)
        found = classes_for_date(target)
        if not found:
            return f"No classes {label}."
        return f"Classes {label}: {', '.join(_describe(c) for c in found)}."
    if action == "clear_timetable":
        _save([])
        return "Cleared your timetable."
    if action == "add_class":
        entry = {"day": parsed["day"], "start": parse_time(parsed["start"]), "end": parse_time(parsed["end"]),
                 "subject": parsed["subject"], "room": parsed["room"]}
        _save(classes + [entry])
        return f"Added {_describe(entry, with_day=True)}."
    # remove_class
    subject, day = parsed["subject"].lower(), parsed["day"]
    kept = [c for c in classes if not (c["subject"].lower() == subject and (not day or c["day"] == day))]
    if len(kept) == len(classes):
        raise AutomationError(f"I don't have a class called {parsed['subject']}{' on ' + day.title() if day else ''}.")
    _save(kept)
    return f"Removed {len(classes) - len(kept)} {parsed['subject']} class{'es' if len(classes) - len(kept) != 1 else ''}."


# ── Reading a timetable with the vision AI ────────────────────────────────────

def _find_file(name: str) -> Path:
    candidate = Path(name.strip("\"'"))
    if candidate.is_file():
        return candidate
    from services.automation import app_finder

    words = re.findall(r"[^\s\"']+", name)
    hits = [Path(p) for p in app_finder._everything(
        ["-path", str(Path.home()), "ext:png;jpg;jpeg;webp;bmp;pdf", *words, r"!\AppData" + "\\"])]
    hits = [p for p in hits if p.is_file()]
    if not hits:
        raise AutomationError(f"I couldn't find a picture or PDF called {name}.")
    return max(hits, key=lambda p: p.stat().st_mtime)  # the newest one


def _image_bytes(file: Path) -> bytes:
    from PIL import Image

    image = Image.open(file).convert("RGB")
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _pdf_pages(file: Path) -> list[bytes]:
    """The first pages of a PDF as JPEGs — a table read as a picture keeps its rows and columns
    (as text, the cells come out jumbled)."""
    import pypdfium2
    from PIL import Image

    pages = []
    pdf = pypdfium2.PdfDocument(str(file))
    try:
        for index in range(min(len(pdf), MAX_PDF_PAGES)):
            image = pdf[index].render(scale=2).to_pil().convert("RGB")
            image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE), Image.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=90)
            pages.append(buffer.getvalue())
    finally:
        pdf.close()
    return pages


async def import_timetable(source: str, provider_name: str, section: str = "") -> str:
    """Read the timetable from the screen or a file with the vision AI, then save it (replacing the old one)."""
    section = section or config.TIMETABLE_SECTION.strip()
    if re.fullmatch(r"(?:the |my |this )?screen", source.lower()):
        from services.vision.screen import capture_screen
        images = [await asyncio.to_thread(capture_screen)]
    else:
        file = await asyncio.to_thread(_find_file, source)
        if file.suffix.lower() == ".pdf":
            images = await asyncio.to_thread(_pdf_pages, file)
        else:
            images = [await asyncio.to_thread(_image_bytes, file)]

    classes = await extract_classes(images, provider_name, section)
    with edit():
        _save(classes)
    days = sorted({c["day"] for c in classes}, key=DAYS.index)
    per_day = "; ".join(f"{d.title()}: {', '.join(c['subject'] for c in classes if c['day'] == d)}" for d in days)
    return (f"Saved your timetable — {len(classes)} classes. {per_day}. Check it with \"what classes do I have on "
            f"Monday\"; fix one with \"remove class …\" / \"add class …\".")
