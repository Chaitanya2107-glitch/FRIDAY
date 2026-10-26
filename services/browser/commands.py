"""Recognize owner commands before ordinary chat, search and learning."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Command:
    kind: str
    text: str = ""
    headless: bool = False


HELP = (
    'Use "browser task <task>" (or \\b <task>), "research <subject>", or '
    '"desktop task <task>". Browsers are visible unless you add "headless" before '
    'the task. Use "browser status", "browser yes" to approve one displayed step, '
    '"browser stop", and "research report". Windows tasks act on the foreground '
    'Notepad or supported file dialog. Research reads at most six pages and saves '
    'a cited report. It never submits forms.'
)


def match_command(message: str) -> Command | None:
    text = message.strip()
    # Preserve task text verbatim. Do not reinterpret quoted/negated examples or
    # strip "headless" out of a subject, URL, or text the owner wants entered.
    text = re.sub(r"^(?:hey\s+)?friday[, ]+", "", text, flags=re.I)
    text = re.sub(r"^please\s+", "", text, flags=re.I)
    control = re.fullmatch(
        r"(?:browser|research|desktop)(?: task)?\s+(status|stop|cancel|no|yes|report|help)", text, re.I)
    if control:
        return Command({"cancel": "stop", "no": "stop"}.get(control[1].lower(), control[1].lower()))
    if re.fullmatch(r"stop (?:the )?(?:browser|research|desktop)(?: task)?", text, re.I):
        return Command("stop")
    match = re.fullmatch(r"(\\b|browser task|desktop task|(?:deep )?research)(?:\s+([\s\S]+))?", text, re.I)
    if not match:
        return None
    kind = {"\\b": "browser", "browser task": "browser", "desktop task": "desktop",
            "research": "research", "deep research": "research"}[match[1].lower()]
    task = (match[2] or "").strip()
    if match[1].lower() == "\\b" and task.lower() in {"yes", "no", "stop", "status", "help", "report"}:
        return Command("stop" if task.lower() == "no" else task.lower())
    headless = task.lower().startswith("headless ")
    if headless:
        task = task[len("headless "):].strip()
    if task.lower().startswith("visibly "):
        task = task[len("visibly "):].strip()
    return Command(kind if task else "help", task, headless)


def is_desktop_command(message: str) -> bool:
    """The popup must restore focus before observing native Windows controls."""
    command = match_command(message)
    return bool(command and (command.kind == "desktop" or
                message.strip().lower().startswith("desktop ")))
