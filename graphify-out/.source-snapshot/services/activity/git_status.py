"""
services/activity/git_status.py

Git for the user's saved projects (services/activity/projects.py). Read-only:
FRIDAY never commits, pushes or changes anything.

  "any uncommitted work?" / "check my projects"   → each project: changed files, commits not pushed
  "any uncommitted work in catjang?"              → just that one
  "what did I change in catjang today?"           → today's commits + what's changed but not committed
  "write a commit message for catjang"            → drafted by the LOCAL model (the diff is your code,
                                                    so it never goes to a cloud AI), copied to the clipboard
An evening notification (GIT_REMINDER_HOUR) lists projects with uncommitted
changes, once a day (services/proactive/watcher.py).
"""

import re
import shutil
import subprocess
from pathlib import Path

from core.config import config
from core.logger import logger
from services.activity import projects
from services.automation.system_control import AutomationError

GIT_ACTIONS = {"git_check", "git_changes"}  # "commit_message" is async (an AI call), run from intent.py
MAX_DIFF_CHARS = 6000  # of the diff shown to the local model
MAX_FILES_LISTED = 5
COMMIT_PROMPT = (
    "Write a git commit message for this diff: a short summary line in the imperative mood (max 60 characters), "
    "then, only if it helps, a blank line and up to 3 short bullet points. Reply with the message only."
)

_CHECK = re.compile(
    r"^(?:(?:do i have |is there |are there |have i got )?any (?:uncommitted|unsaved|unpushed) (?:work|changes|code|commits)"
    r"|(?:check|show)(?: me)?(?: the| my)? (?:git|projects?|repos?)(?: status)?|git status"
    r"|what(?:'s| is) not (?:committed|pushed)(?: yet)?)(?: (?:in|for|on) (?:the |my )?(?P<name>.+?))?$", re.I,
)
_CHANGES = re.compile(
    r"^what (?:did i|have i) (?:change|changed|commit|committed|do|done) (?:in|on|to) (?:the |my )?(?P<name>.+?)"
    r"(?: project)?(?P<when> today| yesterday| this week)?$", re.I,
)
_COMMIT = re.compile(
    r"^(?:write|draft|suggest|make|give me)(?: me)? (?:a )?commit message(?: (?:for|in) (?:the |my )?(?P<name>.+?))?$", re.I,
)
_SINCE = {"today": "midnight", "yesterday": "yesterday midnight", "this week": "1 week ago midnight"}


def match_git_command(text: str) -> dict | None:
    """Git commands. `text` has been through normalize_command(). A named project must be saved."""
    text = text.strip()
    for pattern, action in ((_CHECK, "git_check"), (_CHANGES, "git_changes"), (_COMMIT, "commit_message")):
        if m := pattern.match(text):
            name = (m["name"] or "").strip().lower().removesuffix(" project")
            if name and name not in projects.load():
                return None  # "what did I do in class today" isn't about a project
            parsed = {"type": "system", "action": action, "name": name}
            if action == "git_changes":
                parsed["when"] = (m["when"] or " today").strip()
            return parsed
    return None


# ── Git ───────────────────────────────────────────────────────────────────────

def _git(folder: Path, *args: str) -> str:
    git = shutil.which("git")
    if not git:
        raise AutomationError("Git isn't installed (or isn't on PATH), so I can't check your projects.")
    try:
        result = subprocess.run(
            [git, "-C", str(folder), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AutomationError(f"Git didn't answer for {folder.name}: {e}")
    if result.returncode != 0:
        raise AutomationError(result.stderr.strip() or f"git {args[0]} failed in {folder.name}")
    return result.stdout


def _repos(name: str = "") -> dict[str, Path]:
    """Saved projects that are git repositories (one, if named)."""
    saved = projects.load()
    if not saved:
        raise AutomationError('You haven\'t saved any projects yet. Open one and say "this is a project".')
    chosen = {name: saved[name]} if name else saved
    repos = {n: Path(info["path"]) for n, info in chosen.items() if (Path(info["path"]) / ".git").exists()}
    if not repos:
        raise AutomationError(f"{name or 'None of your projects'} {'is' if name else 'are'} not a git repository.")
    return repos


def status(folder: Path) -> tuple[list[str], int | None]:
    """(changed files, commits not pushed — None if the branch has no upstream)."""
    changed = [line[3:].strip().strip('"') for line in _git(folder, "status", "--porcelain").splitlines() if line.strip()]
    try:
        ahead = int(_git(folder, "rev-list", "--count", "@{upstream}..HEAD").strip())
    except (AutomationError, ValueError):
        ahead = None
    return changed, ahead


def _describe(name: str, changed: list[str], ahead: int | None) -> str:
    parts = []
    if changed:
        files = ", ".join(changed[:MAX_FILES_LISTED]) + (f" and {len(changed) - MAX_FILES_LISTED} more"
                                                        if len(changed) > MAX_FILES_LISTED else "")
        parts.append(f"{len(changed)} uncommitted change{'s' if len(changed) != 1 else ''} ({files})")
    if ahead:
        parts.append(f"{ahead} commit{'s' if ahead != 1 else ''} not pushed")
    return f"{name}: " + ("; ".join(parts) if parts else "all committed")


def check(name: str = "") -> str:
    lines = []
    for project, folder in _repos(name).items():
        try:
            lines.append(_describe(project, *status(folder)))
        except AutomationError as e:
            lines.append(f"{project}: {e}")
    return " ".join(line.rstrip(".") + "." for line in lines)


def changes(name: str, when: str = "today") -> str:
    if not name:
        raise AutomationError('Which project? Say "what did I change in <project> today".')
    folder = _repos(name)[name]
    log = _git(folder, "log", f"--since={_SINCE[when]}", "--pretty=%s").splitlines()
    changed, _ = status(folder)
    stat = _git(folder, "diff", "HEAD", "--shortstat").strip() if changed else ""
    parts = []
    if log:
        shown = "; ".join(log[:MAX_FILES_LISTED]) + (f" (and {len(log) - MAX_FILES_LISTED} more)" if len(log) > MAX_FILES_LISTED else "")
        parts.append(f"{len(log)} commit{'s' if len(log) != 1 else ''} {when}: {shown}")
    if changed:
        parts.append(f"{'Not' if parts else 'not'} committed yet: {stat or f'{len(changed)} files'} "
                     f"({', '.join(changed[:MAX_FILES_LISTED])}{' …' if len(changed) > MAX_FILES_LISTED else ''})")
    return f"In {name}, " + (". ".join(parts) if parts else f"nothing changed {when}") + "."


def run(parsed: dict) -> str:
    return check(parsed["name"]) if parsed["action"] == "git_check" else changes(parsed["name"], parsed["when"])


def uncommitted_summary() -> str | None:
    """For the evening notification: projects with uncommitted changes, or None if all are clean (or none saved)."""
    try:
        repos = _repos()
    except AutomationError:
        return None
    dirty = []
    for name, folder in repos.items():
        try:
            changed, _ = status(folder)
        except AutomationError as e:
            logger.warning(f"Git check of {name} failed: {e}")
            continue
        if changed:
            dirty.append(f"{name} has {len(changed)} uncommitted change{'s' if len(changed) != 1 else ''}")
    return ("; ".join(dirty) + ". Commit before you stop?") if dirty else None


# ── Commit message (local model only) ─────────────────────────────────────────

async def commit_message(name: str) -> str:
    from providers.base_provider import Message
    from providers.registry import get_provider
    from services.automation import clipboard

    if not name:  # fine without a name only when there's one project
        repos = list(_repos())
        if len(repos) != 1:
            raise AutomationError('Which project? Say "write a commit message for <project>".')
        name = repos[0]
    folder = _repos(name)[name]
    diff = _git(folder, "diff", "HEAD")
    untracked = _git(folder, "ls-files", "--others", "--exclude-standard").split()
    if not diff.strip() and not untracked:
        return f"There's nothing to commit in {name}."
    if untracked:
        diff += "\nNew files: " + ", ".join(untracked[:20])
    if config.AI_ASSIST_ONLY:
        changed, ahead = status(folder)
        return _describe(name, changed, ahead) + "\nWrite the commit summary from these changes, Boss."
    if not config.provider_is_configured("ollama"):
        raise AutomationError("Commit messages are written by the local model (your code stays on this PC), "
                              "and Ollama isn't set up.")
    try:
        result = await get_provider("ollama").complete(
            messages=[Message(role="user", content=diff[:MAX_DIFF_CHARS])],
            system_prompt=COMMIT_PROMPT, max_tokens=150, temperature=0.2,
        )
    except Exception as e:
        raise AutomationError(f"The local model couldn't write it (is Ollama running?): {e}")
    message = result.content.strip().strip("`").strip()
    try:
        clipboard.set_text(message)
        copied = " (copied to your clipboard)"
    except Exception:
        copied = ""
    return f"Commit message for {name}{copied}:\n{message}"
