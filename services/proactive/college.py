"""
services/proactive/college.py

Smaller college helpers, on top of the timetable, deadlines, notes and activity log:
  - class links: "DBMS class link is meet.google.com/abc-defg-hij", "join DBMS class",
    "join my class" (the one on now / next today); the class warning gets a [Join] button
  - class start: when a class begins and you're at the laptop, "DBMS started. Start study mode
    for DBMS?" [Yes] [No] (once per class, not while a mode is on)
  - exams: deadlines that look like exams ("DBMS CIE 2 due Oct 12") get a countdown in the
    morning briefing up to EXAM_DAYS ahead
  - "make a revision pack for DBMS" → College\\DBMS\\DBMS revision pack.md (files, videos watched,
    notes, deadlines, marks, attendance, study time, the syllabus) — opened
  - syllabus: "DBMS syllabus is in <file>" reads its units (PDF / Word / text); "what's in DBMS
    unit 2", "DBMS syllabus"
  - "start the DBMS assignment" → makes College\\DBMS\\<the deadline's name>, opens it, marks the
    deadline started
  - profile: "my USN is R24AI123", "my section is II-A" → "type my USN" types it, "what's my USN"
Kept in memory/college.json.
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from core.config import config
from core.logger import logger
from services.automation.system_control import AutomationError
from services.proactive import deadlines, timetable

path = config.MEMORY_DIR / "college.json"  # tests point this elsewhere
EXAM_DAYS = 30
CLASS_START_MINUTES = 5  # a class that started this long ago still gets the study-mode offer
EXAM_WORDS = re.compile(r"\b(?:exam|cie|see|ia|internal|mid ?sem|end ?sem|test|quiz|viva)\b", re.I)
PROFILE_KEYS = {"usn": "USN", "srn": "SRN", "roll number": "roll number", "registration number": "registration number",
                "section": "section", "college email": "college email", "student id": "student ID", "semester": "semester",
                "branch": "branch", "college id": "college ID"}
COLLEGE_ACTIONS = {"set_class_link", "join_class", "revision_pack", "set_syllabus", "show_syllabus", "start_assignment",
                   "set_profile", "show_profile"}

_KEYS = "|".join(sorted(map(re.escape, PROFILE_KEYS), key=len, reverse=True))
_LINK = re.compile(r"^(?:(?:the |my )?(?P<a>.+?) (?:class |meet |lecture )?link is|(?:set|save|add) (?:the |a )?link for "
                   r"(?P<b>.+?)(?: class)?(?: to| as|:)?)\s+(?P<url>\S+)$", re.I)
_JOIN = re.compile(r"^join (?:the |my )?(?:(?P<subject>.+?) )?(?:class|lecture|meet|meeting)$", re.I)
_PACK = re.compile(r"^(?:make|create|build|give me) (?:a |my )?revision (?:pack|notes|sheet) (?:for|on) (?P<subject>.+)$", re.I)
_SYLLABUS_SET = re.compile(r"^(?:the |my )?(?P<subject>.+?) syllabus is (?:in |at )?(?P<file>.+)$"
                           r"|^(?:import|read|load) (?:the |my )?(?P<s2>.+?) syllabus from (?P<f2>.+)$", re.I)
_SYLLABUS_ASK = re.compile(r"^(?:what(?:'s| is) in |show(?: me)? )?(?:the |my )?(?P<subject>.+?) (?:unit|module) (?P<n>\d+)$"
                           r"|^(?:show(?: me)? |what(?:'s| is) )?(?:the |my )?(?P<s2>.+?) syllabus$", re.I)
_ASSIGNMENT = re.compile(r"^(?:start|begin|start working on|work on) (?:the |my )?(?P<what>.+?(?:assignment|project|lab record|"
                         r"report|homework)(?: \d+)?)$", re.I)
_PROFILE_SET = re.compile(rf"^my (?P<key>{_KEYS}) is (?P<value>.+)$", re.I)
_PROFILE_ASK = re.compile(rf"^what(?:'s| is) my (?P<key>{_KEYS})$", re.I)
_UNIT = re.compile(r"^\s*(?:unit|module)[\s\-–:]*(?P<n>\d+|[ivx]+)\b[\s\-–:.]*(?P<title>.*)$", re.I | re.M)
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8}

_offered: set[str] = set()  # classes already offered study mode today


# ── The file ──────────────────────────────────────────────────────────────────

def load() -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError) as e:
        raise AutomationError(f"I couldn't read {path} — is there a typo in it? ({e})") from e
    for key in ("links", "syllabus", "profile"):
        data.setdefault(key, {})
    return data


def _save(data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _subject(said: str) -> str:
    return timetable.subject_named(said.strip(" .'\""))


def profile_value(key: str) -> str | None:
    """ "usn" → the saved USN, for "type my USN" (typing_commands.py)."""
    try:
        return load()["profile"].get(key.lower().strip())
    except AutomationError:
        return None


# ── Class links, class start ──────────────────────────────────────────────────

def link_for(subject: str) -> str | None:
    try:
        return load()["links"].get(subject)
    except AutomationError:
        return None


def class_now_or_next(now: datetime) -> dict | None:
    """The class on right now, else the next one today."""
    today = timetable.classes_for_date(now.date())
    clock = now.strftime("%H:%M")
    return next((c for c in today if c["start"] <= clock < c["end"]), None) or \
        next((c for c in today if c["start"] > clock), None)


def class_start_offer(now: datetime, active: bool, mode_on: bool) -> dict | None:
    """A class that just started, while the user is at the laptop and no mode is on: offer study mode (once)."""
    if not active or mode_on:
        return None
    try:
        today = timetable.classes_for_date(now.date())
    except AutomationError:
        return None
    for c in today:
        start = now.replace(hour=int(c["start"][:2]), minute=int(c["start"][3:]), second=0, microsecond=0)
        key = f"{now.date()} {c['start']} {c['subject']}"
        if timedelta(0) <= now - start <= timedelta(minutes=CLASS_START_MINUTES) and key not in _offered:
            _offered.add(key)
            return {"subject": c["subject"], "text": f"{c['subject']} has started. Start study mode for {c['subject']}?"}
    return None


# ── Exams ─────────────────────────────────────────────────────────────────────

def exam_line(now: datetime) -> str:
    """For the briefing: exams from 3 days (the deadline line has those) up to EXAM_DAYS away."""
    exams = [(datetime.fromisoformat(d["due"]), d["what"]) for d in deadlines.load() if EXAM_WORDS.search(d["what"])]
    upcoming = sorted((due, what) for due, what in exams if deadlines.SOON < due - now <= timedelta(days=EXAM_DAYS))
    if not upcoming:
        return ""
    return "Exams: " + "; ".join(f"{what} in {(due.date() - now.date()).days} days" for due, what in upcoming) + "."


# ── Syllabus ──────────────────────────────────────────────────────────────────

def parse_units(text: str) -> dict[str, str]:
    """ "Unit 2: Normalization …" / "MODULE-II …" sections → {"2": "Normalization …"}."""
    marks = list(_UNIT.finditer(text))
    units = {}
    for i, m in enumerate(marks):
        n = m["n"].lower()
        number = str(_ROMAN.get(n, n))
        body = text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        units.setdefault(number, re.sub(r"\s+", " ", f"{m['title']} {body}").strip())
    return units


def _read_file(name: str) -> str:
    from services.files.extract import extract_text

    candidate = Path(name.strip("\"'"))
    file = candidate if candidate.is_file() else _find_any(name)
    return extract_text(file, file.stat().st_size) or ""


def _find_any(name: str) -> Path:
    """A document by name (PDF / Word / text), found with Everything like the timetable's pictures."""
    from services.automation import app_finder

    words = re.findall(r"[^\s\"']+", name)
    hits = [Path(p) for p in app_finder._everything(
        ["-path", str(Path.home()), "ext:pdf;docx;doc;txt;md", *words, r"!\AppData" + "\\"])]
    hits = [p for p in hits if p.is_file()]
    if not hits:
        raise AutomationError(f"I couldn't find a document called {name}.")
    return max(hits, key=lambda p: p.stat().st_mtime)


# ── Revision pack ─────────────────────────────────────────────────────────────

def revision_pack(subject: str, log, now: datetime) -> Path:
    """Write College\\<subject>\\<subject> revision pack.md from everything FRIDAY knows about the subject."""
    from services.activity import study
    from services.files import filing
    from services.memory import notes
    from services.proactive import attendance

    forms = timetable.aliases(subject)
    folder = filing.COLLEGE_DIR / filing._folder_name(subject)
    lines = [f"# {subject} — revision pack", f"_Made by FRIDAY on {now:%A, %d %B %Y}_", ""]

    def section(title: str, items: list[str]) -> None:
        if items:
            lines.extend([f"## {title}", *[f"- {item}" for item in items], ""])

    data = load()
    units = data["syllabus"].get(subject, {})
    section("Syllabus", [f"Unit {n}: {text[:300]}" for n, text in sorted(units.items(), key=lambda i: int(i[0]))])
    files = sorted((p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() != ".md"),
                   key=lambda p: p.stat().st_mtime, reverse=True) if folder.is_dir() else []
    section("Your files", [str(p.relative_to(folder)) for p in files[:40]])
    watched = log.search("kind = 'web' AND target LIKE '%youtube.%' AND at >= ?", [(now - timedelta(days=120)).isoformat()])
    section("Videos you watched", list(dict.fromkeys(
        r["title"].removesuffix(" - YouTube") for r in watched if r["title"] and timetable.mentions_subject(r["title"], forms)))[:20])
    section("Notes", [n["text"] for n in notes.load() if timetable.mentions_subject(n["text"], forms)])
    section("Deadlines", [f"{d['what']} — {deadlines.when(datetime.fromisoformat(d['due']), now)}"
                          for d in deadlines.load() if timetable.mentions_subject(d["what"], forms)])
    try:
        record = attendance.load()
        counts = attendance.counts(record).get(subject)
        marks = [m for m in record["marks"] if m["subject"] == subject]
    except AutomationError:
        counts, marks = None, []
    section("Marks and attendance", [f"{m['exam']}: {m['got']:g}/{m['out_of']:g}" for m in marks]
            + ([attendance.status(subject, *counts)] if counts else []))
    studied = study.totals(log.study_rows(now - timedelta(days=120), now), [subject]).get(subject)
    section("Study time (last 4 months)", [study._duration(studied)] if studied else [])
    folder.mkdir(parents=True, exist_ok=True)
    pack = folder / f"{filing._folder_name(subject)} revision pack.md"
    pack.write_text("\n".join(lines), encoding="utf-8")
    return pack


# ── Commands ──────────────────────────────────────────────────────────────────

def match_college_command(text: str) -> dict | None:
    """`text` has been through normalize_command()."""
    text = text.strip().rstrip("?.!")
    if m := _PROFILE_SET.match(text):
        return {"type": "system", "action": "set_profile", "key": m["key"].lower(), "value": m["value"].strip()}
    if m := _PROFILE_ASK.match(text):
        return {"type": "system", "action": "show_profile", "key": m["key"].lower()}
    if (m := _LINK.match(text)) and re.search(r"\.|://", m["url"]):
        return {"type": "system", "action": "set_class_link", "subject": m["a"] or m["b"], "url": m["url"]}
    if m := _JOIN.match(text):
        return {"type": "system", "action": "join_class", "subject": m["subject"] or ""}
    if m := _PACK.match(text):
        return {"type": "system", "action": "revision_pack", "subject": m["subject"]}
    if m := _SYLLABUS_SET.match(text):
        return {"type": "system", "action": "set_syllabus", "subject": m["subject"] or m["s2"], "file": m["file"] or m["f2"]}
    if (m := _SYLLABUS_ASK.match(text)) and _is_subject(m["subject"] or m["s2"]):
        return {"type": "system", "action": "show_syllabus", "subject": m["subject"] or m["s2"], "unit": m["n"] or ""}
    if (m := _ASSIGNMENT.match(text)) and any(_is_subject(w) for w in re.findall(r"[\w+]+", m["what"])):
        return {"type": "system", "action": "start_assignment", "what": m["what"]}
    return None


def _is_subject(said: str) -> bool:
    return bool(said) and timetable.subject_named(said).lower() in {s.lower() for s in timetable.subjects()}


def run(parsed: dict, log=None, now: datetime | None = None) -> str:
    now = now or datetime.now()
    action, data = parsed["action"], load()
    if action == "set_profile":
        data["profile"][parsed["key"]] = parsed["value"]
        _save(data)
        return f'Saved your {PROFILE_KEYS[parsed["key"]]}. Say "type my {parsed["key"]}" to type it anywhere.'
    if action == "show_profile":
        value = data["profile"].get(parsed["key"])
        return f"Your {PROFILE_KEYS[parsed['key']]} is {value}." if value else \
            f'I don\'t know your {PROFILE_KEYS[parsed["key"]]} yet. Say "my {parsed["key"]} is …".'
    if action == "set_class_link":
        subject, url = _subject(parsed["subject"]), parsed["url"]
        data["links"][subject] = url if "//" in url else "https://" + url
        _save(data)
        return f"Saved the {subject} class link. The class warning will have a Join button."
    if action == "join_class":
        return _join(parsed["subject"], data, now)
    if action == "set_syllabus":
        subject = _subject(parsed["subject"])
        units = parse_units(_read_file(parsed["file"]))
        if not units:
            raise AutomationError("I couldn't find any units in that file (I look for lines like \"Unit 2\" or \"Module II\").")
        data["syllabus"][subject] = units
        _save(data)
        return f"Saved the {subject} syllabus: units {', '.join(sorted(units, key=int))}."
    if action == "show_syllabus":
        subject = _subject(parsed["subject"])
        units = data["syllabus"].get(subject)
        if not units:
            return f'I don\'t have the {subject} syllabus. Say "{subject} syllabus is in <file name>".'
        if parsed["unit"]:
            text = units.get(parsed["unit"])
            return f"{subject} unit {parsed['unit']}: {text[:600]}" if text else f"{subject} has no unit {parsed['unit']}."
        return f"{subject}: " + " ".join(f"Unit {n}: {t[:80]}…" for n, t in sorted(units.items(), key=lambda i: int(i[0])))
    if action == "revision_pack":
        from services.activity.log import activity_log
        pack = revision_pack(_subject(parsed["subject"]), log or activity_log, now)
        os.startfile(pack)
        return f"Made your revision pack: {pack.name}."
    return _start_assignment(parsed["what"], now)


def _join(said: str, data: dict, now: datetime) -> str:
    from services.automation.system_control import system

    if said:
        subject = _subject(said)
    else:
        c = class_now_or_next(now)
        if not c:
            raise AutomationError("There's no class on right now or later today.")
        subject = c["subject"]
    url = data["links"].get(subject)
    if not url:
        raise AutomationError(f'I don\'t have a link for {subject}. Say "{subject} class link is meet.google.com/…".')
    system.open_url(url)
    return f"Joining {subject}."


def _start_assignment(what: str, now: datetime) -> str:
    from services.files import filing

    subject = next((timetable.subject_named(w) for w in re.findall(r"[\w+]+", what) if _is_subject(w)), None)
    items = deadlines.load()
    forms = timetable.aliases(subject) if subject else []
    wanted = set(re.findall(r"[a-z0-9]+", what.lower())) - {"the", "my", "assignment", "project"}
    match = max((d for d in items if timetable.mentions_subject(d["what"], forms)),
                key=lambda d: len(wanted & set(re.findall(r"[a-z0-9]+", d["what"].lower()))), default=None)
    name = match["what"] if match else what.strip()
    folder = filing.COLLEGE_DIR / filing._folder_name(subject or "Other") / filing._folder_name(name[:1].upper() + name[1:])
    folder.mkdir(parents=True, exist_ok=True)
    os.startfile(folder)
    if match:
        with deadlines.edit():
            items = deadlines.load()
            found = [d for d in items if (d.get("id") == match["id"] if match.get("id") else
                                         (d["what"], d["due"]) == (match["what"], match["due"]))]
            if len(found) != 1:
                raise AutomationError("The assignment deadline changed. Check deadlines before trying again.")
            match = found[0]
            match["started"] = now.isoformat(timespec="minutes")
            deadlines._save(items)
        return f"Started {name}: folder ready, due {deadlines.when(datetime.fromisoformat(match['due']), now)}."
    logger.info(f"Assignment folder made without a deadline: {folder}")
    return f'Made a folder for {name}. No deadline for it yet — say "{name} due Friday 11:59pm" to add one.'
