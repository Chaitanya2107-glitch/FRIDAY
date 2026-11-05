"""
interfaces/cli/friday.py

`friday` in the terminal — talks to the running FRIDAY (the local API), so commands, chat,
files, memory and the rest all work, and replies print here instead of being spoken.

  friday open spotify
  friday what's due this week
  git diff | friday "review this"
  npm run build 2>&1 | friday "why did this fail"
  friday                      → a small back-and-forth (empty line or Ctrl+C to leave)

Piped text is added to the question (the end of it, if it's long: that's where errors are).
It goes to whichever AI answers the chat, so don't pipe secrets.
Uses the same local API configuration as the desktop. The PowerShell profile has a `friday` function
that runs it with FRIDAY's own Python.
"""

import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.config import config

URL = f"http://{config.API_HOST}:{config.API_PORT}/api/v1/chat"
MAX_MESSAGE = 4000          # the API's limit
MAX_REPLY_TOKENS = 1000
TIMEOUT_SECONDS = 180       # free models can think for a while


def build_message(question: str, piped: str) -> str:
    """The question, with piped text attached (its end, if it doesn't fit)."""
    question = question.strip() or "Explain this."
    piped = piped.strip()
    if not piped:
        return question[:MAX_MESSAGE]
    room = MAX_MESSAGE - len(question) - 40
    if len(piped) > room:
        piped = "…" + piped[-(room - 1):]
    return f"{question}\n\nTerminal output:\n{piped}"


def ask(message: str) -> str:
    request = urllib.request.Request(URL, method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"message": message, "max_tokens": MAX_REPLY_TOKENS}).encode())
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=TIMEOUT_SECONDS) as reply:
            return json.loads(reply.read())["response"]
    except urllib.error.HTTPError as e:
        try:
            return f"FRIDAY: {json.loads(e.read()).get('message', e.reason)}"
        except ValueError:
            return f"FRIDAY answered with an error ({e.code})."
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return "FRIDAY isn't running. Start it from launch_friday.vbs (or the Start menu) and try again."


def _read(stdin) -> str:
    """Piped text as UTF-8 (the profile's `friday` function sends UTF-8), whatever Windows' code page is."""
    raw = stdin.buffer.read() if hasattr(stdin, "buffer") else stdin.read()
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw


def main(argv: list[str], stdin) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    question = " ".join(argv)
    piped = "" if stdin is None or stdin.isatty() else _read(stdin)
    if question or piped.strip():
        print(ask(build_message(question, piped)))
        return 0
    try:  # nothing given: a small back-and-forth
        while line := input("you> ").strip():
            print(ask(line))
    except (EOFError, KeyboardInterrupt):
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdin))
