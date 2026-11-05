"""
services/automation/writer.py

"write an email asking my boss for Friday off" — the AI writes the text and
FRIDAY types it into the app the user is using. Uses the chat provider (with
failover); the reply is cleaned so only the text itself gets typed.
"""

import re
from datetime import datetime

from core.logger import logger
from providers.base_provider import Message
from providers.failover import complete_with_failover

MAX_TOKENS = 1200
WRITER_PROMPT = (
    "You write text that will be typed straight into the app the user is using: an email, "
    "a chat message, a document, a code editor. Output only that text. No introduction such as "
    "\"Here's your email\", no explanation, no quotation marks around it, no markdown, no "
    "asterisks. Use plain line breaks. For code, output only the code. Match the length the "
    "user asked for; if they didn't say, keep it short. If details like names are missing, "
    "write around them naturally instead of leaving [placeholders]."
)
PREAMBLE = re.compile(r"^(?:sure|okay|ok|certainly|of course)?[,!.]?\s*here(?:'s| is)\b[^\n]*:\s*\n+", re.IGNORECASE)
FENCE = re.compile(r"^```[\w+-]*\n(?P<body>.*?)\n?```$", re.DOTALL)


def clean(text: str) -> str:
    """Strip what a model adds around the text despite the prompt."""
    text = (text or "").strip()
    text = PREAMBLE.sub("", text, count=1).strip()
    fenced = FENCE.match(text)
    if fenced:
        text = fenced.group("body").strip("\n")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    if len(text) >= 2 and text[0] == "“" and text[-1] == "”":
        text = text[1:-1].strip()
    return text


async def write(request: str, provider_name: str) -> str:
    """The text the AI wrote for `request` (e.g. "an email asking for Friday off")."""
    today = datetime.now().strftime("%A, %B %d, %Y")
    result = await complete_with_failover(
        provider_name,
        [Message(role="user", content=f"Write {request}")],
        f"{WRITER_PROMPT}\nToday's date is {today}.",
        MAX_TOKENS,
    )
    return clean(result.content)


async def resolve_writing(actions: list[dict], provider_name: str) -> list[dict]:
    """Have the AI write the text for each write_text action, turning it into text to type."""
    resolved = []
    for action in actions:
        if action.get("action") == "write_text" and str(action.get("request", "")).strip():
            text = await write(str(action["request"]), provider_name)
            if not text:
                logger.warning("The AI wrote nothing to type")
                continue
            action = {**action, "action": "type_written", "text": text}
        resolved.append(action)
    return resolved
