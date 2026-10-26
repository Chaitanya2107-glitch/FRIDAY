"""
services/files/filing.py

Smart download filing: when a document lands in Downloads (services/watch/auto.py), guess
where it belongs and ask — "Move Finance_Unit3.pdf to College\\Finance? [Move it] [Leave it]".
Nothing moves without the click (the buttons also work from Telegram).

The guess, locally: a subject (timetable subjects + "my subjects are …", by name or initials)
or a saved project named in the file name counts 3, a subject in its first page counts 1;
one clear winner or no suggestion. Subjects go to Documents\\College\\<Subject>, made on first use.
"""

import re
import shutil
from datetime import datetime
from pathlib import Path

from core.logger import logger
from services.activity import projects
from services.automation.system_control import AutomationError
from services.files.extract import extract_text
from services.proactive import timetable

DOC_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".odt", ".txt", ".md"}
COLLEGE_DIR = Path.home() / "Documents" / "College"  # tests point this elsewhere
PREVIEW_CHARS = 3000
NAME_WEIGHT, TEXT_WEIGHT = 3, 1


def _folder_name(subject: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", subject).strip(" .") or "Other"


def suggest(path: Path) -> Path | None:
    """The folder this download probably belongs in, or None. Blocking (reads the first page)."""
    if path.suffix.lower() not in DOC_EXTENSIONS:
        return None
    name = path.stem.replace("_", " ")
    try:
        text = (extract_text(path, path.stat().st_size) or "")[:PREVIEW_CHARS]
    except Exception as e:  # a half-written or odd file: go by its name
        logger.info(f"Filing: couldn't read {path.name}: {e}")
        text = ""
    scores: dict[Path, int] = {}
    for subject in timetable.subjects():
        forms = timetable.aliases(subject)  # "DS" and "Data Structures"
        score = NAME_WEIGHT * timetable.mentions_subject(name, forms) + TEXT_WEIGHT * timetable.mentions_subject(text, forms)
        if score:
            scores[COLLEGE_DIR / _folder_name(subject)] = score
    for project, info in projects.load().items():
        if timetable.mentions(name, project):
            scores[Path(info["path"])] = scores.get(Path(info["path"]), 0) + NAME_WEIGHT
    if not scores:
        return None
    best = max(scores.values())
    winners = [folder for folder, score in scores.items() if score == best]
    return winners[0] if len(winners) == 1 else None  # a tie: better to ask nothing than guess


def describe(folder: Path) -> str:
    """ "College\\Finance" for subject folders, the full path otherwise."""
    try:
        return str(folder.relative_to(COLLEGE_DIR.parent))
    except ValueError:
        return str(folder)


def tidy_name(stem: str, subject: str | None) -> str:
    """ "Unit2_notes (3)" in DBMS → "DBMS - Unit 2 notes": no copy numbers or underscores, the subject in front."""
    stem = re.sub(r"\s*\(\d+\)$|\s*-\s*copy$", "", stem, flags=re.I)
    stem = re.sub(r"[_]+", " ", stem)
    stem = re.sub(r"(?<=[a-z])(?=\d)", " ", stem, flags=re.I)  # "Unit2" → "Unit 2"
    stem = re.sub(r"\s+", " ", stem).strip(" -.")
    if subject and not timetable.mentions_subject(stem, timetable.aliases(subject)):
        stem = f"{subject} - {stem}"
    return _folder_name(stem)


def move(source: str, folder: str, rename: bool = False) -> str:
    """The [Move it] / [Move & rename] buttons. Paths come from FRIDAY's own record of the notification."""
    src, dest_dir = Path(source), Path(folder)
    if not src.is_file():
        raise AutomationError(f"{src.name} isn't in Downloads any more.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    subject = dest_dir.name if dest_dir.parent == COLLEGE_DIR else None
    stem = tidy_name(src.stem, subject) if rename else src.stem
    target, n = dest_dir / f"{stem}{src.suffix}", 1
    while target.exists():
        target, n = dest_dir / f"{stem} ({n}){src.suffix}", n + 1
    shutil.move(str(src), str(target))
    logger.info(f"Filed {src.name} → {target}")
    return f"Moved {src.name} to {describe(dest_dir)}" + (f" as {target.name}." if rename else ".")


# ── Screenshots ───────────────────────────────────────────────────────────────
# A screenshot taken during a class (timetable) or a study session for a subject ("study mode
# for DBMS") is moved to College\<Subject>\Screenshots at once — lecture slides end up with
# the subject. Others stay where they are. services/watch/auto.py spots new ones.

SCREENSHOT_EXTENSIONS = {".png", ".jpg", ".jpeg"}


def subject_now(now: datetime) -> str | None:
    from services.automation import modes  # avoid an import cycle at startup

    mode = modes.active()
    if mode and mode.get("subject"):
        return mode["subject"]
    clock = now.strftime("%H:%M")
    try:
        return next((c["subject"] for c in timetable.classes_for_date(now.date())
                     if c["start"] <= clock < c["end"]), None)
    except AutomationError:
        return None


def file_screenshot(path: Path, now: datetime | None = None) -> Path | None:
    """Move a new screenshot to its subject's folder; the folder it went to, or None if it stays."""
    now = now or datetime.now()
    subject = subject_now(now) if path.suffix.lower() in SCREENSHOT_EXTENSIONS else None
    if not subject:
        return None
    folder = COLLEGE_DIR / _folder_name(subject) / "Screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    target, n = folder / f"{subject} {now:%Y-%m-%d %H-%M-%S}{path.suffix.lower()}", 1
    while target.exists():
        target, n = folder / f"{subject} {now:%Y-%m-%d %H-%M-%S} ({n}){path.suffix.lower()}", n + 1
    try:
        shutil.move(str(path), str(target))
    except OSError as e:  # still being written, or gone
        logger.warning(f"Couldn't file screenshot {path.name}: {e}")
        return None
    logger.info(f"Filed screenshot → {target}")
    return folder
