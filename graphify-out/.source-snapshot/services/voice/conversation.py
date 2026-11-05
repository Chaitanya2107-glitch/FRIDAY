"""
services/voice/conversation.py

Conversation mode: a back-and-forth by voice without pressing the hotkey each time. The tray runs the
loop (interfaces/tray/tray.py): after each reply FRIDAY finishes speaking, beeps and listens again.
It starts from the tray, Ctrl+Alt+C, or by saying / typing "let's talk"; it ends with "bye",
"that's all", Ctrl+Alt+C again, or two silences in a row.
"""

import re

from services.automation.command_words import normalize_command, rephrase_command

_START = re.compile(r"^(?:(?:hey |ok(?:ay)? )?friday,? )?(?:let'?s (?:talk|chat|have a (?:chat|conversation))"
                    r"|(?:start |turn on |enable )?conversation mode(?: on)?|talk to me|can we talk)$", re.I)
_END = re.compile(r"^(?:(?:ok(?:ay)?,? )?(?:bye|goodbye|bye bye|see you|see ya|later|talk later|talk to you later)"
                  r"(?:,? friday)?|that'?s all(?: for now)?|that'?ll be all|we'?re done|i'?m done|stop talking"
                  r"|end (?:the )?conversation|(?:stop |end |exit |turn off )conversation mode|conversation mode off)$", re.I)

START_REPLY = "I'm all ears, Boss."
END_REPLY = "Talk later, Boss."


def match_conversation(text: str) -> str | None:
    """"start", "end", or None."""
    text = " ".join(text.replace("’", "'").split()).strip(" .!?,")
    for candidate in (text, normalize_command(rephrase_command(text))):
        if _START.match(candidate):
            return "start"
        if _END.match(candidate):
            return "end"
    return None


if __name__ == "__main__":
    assert match_conversation("Let's talk.") == "start"
    assert match_conversation("Hey Friday, let's chat") == "start"
    assert match_conversation("conversation mode") == "start"
    assert match_conversation("Okay, bye Friday!") == "end"
    assert match_conversation("That's all for now.") == "end"
    assert match_conversation("let's talk about my exam") is None
    assert match_conversation("bye bye birdie song") is None
    print("ok")
