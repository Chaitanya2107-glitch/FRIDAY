"""
services/automation/results.py

What running a command gives back — shared by intent.py (deciding) and actions.py (doing).
"""

from typing import NamedTuple


class ActionResult(NamedTuple):
    success: bool
    message: str
    memory_message: str | None = None  # stored in chat history instead of `message` when set
    # False for replies that change every time (stats, track names): not worth caching as speech
    repeatable: bool = True
    # Keys for the client to type into the focused app: {"text": ...} or {"keys": ..., "times": n}
    keyboard: tuple = ()
    # Said out loud even when typed ("read this"); by voice it's said instead of `message` ("" = say nothing)
    speech: str | None = None
