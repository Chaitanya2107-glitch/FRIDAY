"""
services/activity/ask.py

Questions about what the user did, answered from the activity log
(services/activity/log.py) — locally, without an AI model, since page and
window titles are private:

  "what was the repo I looked at on Tuesday?"       → GitHub pages, Tuesday
  "which file did I open this morning for DBMS?"    → opened files with "dbms"
  "what video did I watch last night?"              → YouTube titles
  "what song was I listening to yesterday?"         → Spotify window titles
  "when did I last open catjang?"                   → the most recent match
  "how long did I spend on YouTube yesterday?"      → time in the foreground

A question is: a time ("yesterday", "this morning", "on Tuesday", "last week";
default the past 7 days), what kind of thing (repo, video, song, file, site,
app, game), and topic words ("DBMS", "catjang") that must appear in the title,
site, app, category or project.
"""

import re
from datetime import datetime, timedelta

ACTIVITY_QUESTION = "ask_activity"
MAX_LISTED = 5
MAX_TITLE = 80  # replies are also spoken
DEFAULT_DAYS = 7

# A question about the user's own past activity: a question word, then "I" + a past-activity verb
_VERB = (r"(?:open(?:ed)?|visit(?:ed)?|watch(?:ed|ing)?|look(?:ed|ing)? at|see|saw|read(?:ing)?|use[d]?|"
         r"search(?:ed|ing)? for|search(?:ed)?|play(?:ed|ing)?|listen(?:ed|ing)? to|browse[d]?|work(?:ed|ing)? on|"
         r"spen[dt](?: time)?(?: on)?|have open|had open|go to|went to|check(?:ed)?(?: out)?)")
_QUESTION = re.compile(
    rf"^(?:what|which|when|where|how long|how much time|show me|list|tell me|find)\b.*?"
    rf"\b(?:did i|have i|i|was i|were i)(?: \w+)?? {_VERB}\b", re.I,
)
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_PARTS = {"morning": (5, 12), "afternoon": (12, 17), "evening": (17, 24), "night": (18, 29)}  # 29 = 5 am next day

# What kind of thing is asked about → (SQL condition, what to call it). First match wins.
_REAL_FILE = "kind = 'file' AND target NOT LIKE 'ms-%' AND target NOT LIKE 'http%' AND target NOT LIKE '{%'"
_KINDS = [
    (r"\b(?:repo|repos|repository|repositories)\b|\bgithub\b",
     "(kind = 'web' AND target LIKE '%github.com%' AND title LIKE '%/%')", "GitHub repos"),  # "owner/repo" pages
    (r"\bsearch(?:ed|ing)?\b|\bgoogled\b",
     "(kind = 'web' AND (title LIKE '% - Google Search' OR title LIKE '% - Bing'))", "searches"),
    (r"\b(?:video|videos|youtube|watch|watched|watching)\b",
     # the history entry (what was watched) and the browser window (how long it was in front)
     "((kind = 'web' AND target LIKE '%youtube.%' AND title LIKE '% - YouTube') "
     "OR (kind = 'app' AND title LIKE '% - YouTube - %'))", "YouTube"),
    (r"\b(?:song|songs|music|track|tracks|listen|listened|listening)\b",
     "(kind = 'app' AND app = 'spotify' AND title NOT LIKE 'Spotify%')", "music"),
    (r"\bpdfs?\b", f"({_REAL_FILE} AND target LIKE '%.pdf%')", "PDFs"),
    (r"\b(?:file|files|document|documents|doc|docs|ppt|slides)\b", f"({_REAL_FILE})", "files"),
    (r"\b(?:site|sites|website|websites|page|pages|link|url)\b", "kind = 'web'", "sites"),
    (r"\b(?:game|games|gaming)\b|\bplayed\b", "(kind IN ('app', 'launch') AND category = 'gaming')", "games"),
    (r"\b(?:app|apps|program|programs|application|applications)\b", "(kind = 'app')", "apps"),
]
_SUFFIXES = re.compile(r"\s+-\s+(?:YouTube|Google Search|Bing)$|\s+\(\d+\)$", re.I)
_SPINNER = re.compile(r"^[^\w(\[]+")  # "✳ Build next", "◐ Build next" (Claude Code's status marks)
# Words that never narrow the search (question words, verbs, time words, kind words, filler)
_STOP = set("""
a an the that this those these it its of for on in at to from with about into by my me i i'm was were is are be been
what which when where who how long much time show list tell find did do does have had has last first latest recent
recently earlier ago lately just again some any one ones thing things stuff something there then so you your can could
open opened visit visited watch watched watching look looked looking see saw seen read reading use used search searched
searching play played playing listen listened listening browse browsed work worked working on spend spent go went
check checked out today yesterday tonight morning afternoon evening night week weekend days day google googled
repo repos repository github video videos youtube song songs music track file files document documents doc docs
pdf pdfs ppt slides site sites website websites page pages link url game games gaming app apps program programs
application
""".split()) | set(_WEEKDAYS) | {"mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun"}
_BROWSER_SUFFIX = re.compile(r"\s+-\s+(?:Google Chrome|Microsoft​? Edge|Mozilla Firefox|Brave)$", re.I)
_YOUTUBE_COUNT = re.compile(r"^\(\d+\)\s*")  # "(436) YouTube": the unread-notifications count


def match_activity_question(text: str) -> dict | None:
    """ "what was the repo I looked at on tuesday" → an ask_activity action. `text` is normalized."""
    if _QUESTION.search(text.strip()):
        return {"type": "system", "action": ACTIVITY_QUESTION, "question": text.strip()}
    return None


# ── Parsing the question ──────────────────────────────────────────────────────

def time_window(question: str, now: datetime) -> tuple[datetime, datetime, str]:
    """(start, end, how to say it) for the time the question is about."""
    q = question.lower()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day, label = None, None

    if re.search(r"\blast night\b", q):
        day, label, part = today - timedelta(days=1), "last night", "night"
    else:
        part = next((p for p in _PARTS if re.search(rf"\b(?:this |in the |at )?{p}\b", q)), None)
        if "tonight" in q:
            part = "evening"
        if re.search(r"\byesterday\b", q):
            day, label = today - timedelta(days=1), "yesterday"
        elif m := re.search(r"\b(\d+) days? ago\b", q):
            day, label = today - timedelta(days=int(m[1])), f"{m[1]} days ago"
        elif m := next((m for m in re.finditer(rf"\b(last |on )?({'|'.join(_WEEKDAYS)})\b", q)
                        if m[1] or m[2] != "friday"), None):  # a bare "friday" is the assistant's name
            back = (today.weekday() - _WEEKDAYS.index(m[2])) % 7
            if back == 0 and m[1] and m[1].strip() == "last":
                back = 7
            day, label = today - timedelta(days=back), "today" if back == 0 else f"on {m[2].title()}"
        elif re.search(r"\blast week\b", q):
            start = today - timedelta(days=today.weekday() + 7)
            return start, start + timedelta(days=7), "last week"
        elif re.search(r"\bthis week\b", q):
            return today - timedelta(days=today.weekday()), now, "this week"
        elif re.search(r"\btoday\b|\bthis (?:morning|afternoon|evening)\b|\btonight\b", q) or part:
            day, label = today, "today"

    if day is None:
        return today - timedelta(days=DEFAULT_DAYS - 1), now, "in the past week"
    if part:
        start_hour, end_hour = _PARTS[part]
        phrase = {"today": f"this {part}", "yesterday": f"yesterday {part}"}.get(label, f"{label} {part}")
        return day + timedelta(hours=start_hour), day + timedelta(hours=end_hour), label if label == "last night" else phrase
    return day, day + timedelta(days=1), label


def kind_filter(question: str) -> tuple[str | None, str | None]:
    """(SQL condition, name) for the kind of thing asked about; (None, None) = anything."""
    q = question.lower()
    return next(((condition, name) for pattern, condition, name in _KINDS if re.search(pattern, q)), (None, None))


def topic_words(question: str) -> list[str]:
    words = re.findall(r"[\w.+#-]+", question.lower())
    return [w.strip(".") for w in words if w.strip(".") not in _STOP and not w.isdigit() and len(w.strip(".")) > 1]


# ── Answering ─────────────────────────────────────────────────────────────────

def answer(question: str, log, now: datetime | None = None) -> str:
    now = now or datetime.now()
    start, end, when = time_window(question, now)
    kind, kind_name = kind_filter(question)
    words = topic_words(question)
    q = question.lower()

    conditions = ["at >= ?", "at < ?", "kind != 'command'"]
    params: list = [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")]
    if kind:
        conditions.append(kind)
    topic = []
    for word in words:
        topic.append("(LOWER(COALESCE(title,'')) LIKE ? OR LOWER(COALESCE(target,'')) LIKE ? "
                     "OR LOWER(COALESCE(app,'')) LIKE ? OR category = ? OR project = ?)")
        params += [f"%{word}%"] * 3 + [word, word]
    rows = log.search(" AND ".join(conditions + topic), params)
    if not rows and len(words) > 1:  # every word is too strict — any of them
        rows = log.search(" AND ".join(conditions + ["(" + " OR ".join(topic) + ")"]), params)

    about = " ".join(words) or kind_name or "that"
    if not rows:
        return f"I don't see any {about} {when}." if kind_name and not words else \
            f"I don't see anything matching {about} {when}."

    if re.match(r"^(?:how long|how much time)\b", q):
        seconds = sum(r["duration_s"] or 0 for r in rows if r["kind"] == "app")
        if seconds < 60:
            return f"Less than a minute on {about} {when}, as far as I saw (time counts while that window is in front)."
        return f"You spent {_duration(seconds)} on {about} {when}."

    if kind_name == "apps":  # which apps: by time used, not every window title
        totals: dict[str, float] = {}
        for row in rows:
            if row["category"] not in ("system",):
                totals[row["app"]] = totals.get(row["app"], 0) + (row["duration_s"] or 0)
        ranked = [f"{app} {_duration(secs)}" for app, secs in sorted(totals.items(), key=lambda i: -i[1]) if secs >= 60]
        return f"{when[:1].upper()}{when[1:]} you used: {', '.join(ranked[:8])}." if ranked else \
            f"I don't see any apps used for more than a minute {when}."

    items = _distinct(rows)
    one_day = (end - start) <= timedelta(days=1, hours=6)  # then the time alone is enough
    if q.startswith("when"):
        at, text = items[0]
        return f"Last time was {_when(at, now)}: {text}."
    listed = "; ".join(f"{_when(at, now, clock_only=one_day)} — {text}" for at, text in items[:MAX_LISTED])
    more = f" (and {len(items) - MAX_LISTED} more)" if len(items) > MAX_LISTED else ""
    return f"{when[:1].upper()}{when[1:]}: {listed}{more}."


def _describe(row) -> str | None:
    title = _BROWSER_SUFFIX.sub("", row["title"] or "")
    title = _SPINNER.sub("", _SUFFIXES.sub("", _YOUTUBE_COUNT.sub("", title))).strip()
    if len(title) > MAX_TITLE:
        title = title[:MAX_TITLE - 1].rstrip() + "…"
    if row["kind"] == "web":
        site = (row["target"] or "").removeprefix("www.")
        if not title or title.lower() in site or site.split(".")[0] in title.lower().replace(" ", ""):
            return title if title and title.lower() not in site else site or None  # "YouTube" on youtube.com
        return f"{title} ({site})"
    if row["kind"] == "file":
        return _SUFFIXES.sub("", row["target"] or "") or None
    if row["kind"] == "launch":
        return f"opened {row['app']}"
    if row["app"] == "spotify":
        return title if title and not title.lower().startswith("spotify") else None
    return f"{title} ({row['app']})" if title else row["app"]


def _distinct(rows) -> list[tuple[datetime, str]]:
    """Newest first, each thing once."""
    seen, items = set(), []
    for row in rows:  # log.search returns newest first
        text = _describe(row)
        key = re.sub(r"\s*\([^)]*\)$", "", text or "").lower()  # the same video as a page and as a window
        if text and key not in seen:
            seen.add(key)
            items.append((datetime.fromisoformat(row["at"]), text))
    return items


def _when(at: datetime, now: datetime, clock_only: bool = False) -> str:
    clock = at.strftime("%I:%M %p").lstrip("0").lower()
    if clock_only:
        return clock
    days = (now.date() - at.date()).days
    if days == 0:
        return f"today {clock}"
    if days == 1:
        return f"yesterday {clock}"
    if days < 7:
        return f"{at.strftime('%A')} {clock}"
    return f"{at.strftime('%b')} {at.day}, {clock}"


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"
