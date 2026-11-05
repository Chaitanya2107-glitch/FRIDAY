"""Explicit engine commands own their payload before typing/search/action parsing."""

import re

from services.automation.results import ActionResult
from services.computation.engine import calculate

HELP = '''FRIDAY local computation engine — no LLM or network required.

calculate (1/3 + 1/6)^2
math simplify sin(x)^2 + cos(x)^2
math expand (x + 1)^3
math factor x^2 - 9
solve x^2 - 5*x + 6 = 0 for x
differentiate x^3 + sin(x) wrt x [order 2]
integrate x^2 wrt x [from 0 to 1]
limit sin(x)/x as x -> 0 [side left|right]
vector dot|cross|angle|add|projection [1,2,3]; [4,5,6]
vector norm|normalize [3,4]
matrix determinant|inverse|transpose [[1,2],[3,4]]
matrix multiply [[1,2],[3,4]]; [[2,0],[0,2]]
matrix solve [[2,1],[1,-1]]; [5,1]
stats [2,4,4,4,5,5,7,9]
convert 36 km/h to m/s
convert 25 C to F
physics force mass=10 acceleration=3
physics kinetic mass=2 speed=3
physics potential mass=2 height=10 [gravity=9.80665]
physics momentum mass=2 velocity=-3
physics ohm current=2 resistance=5
physics power voltage=12 current=2
physics wave frequency=50 wavelength=2
physics gas moles=1 temperature=300 volume=0.025
physics projectile speed=20 angle=45 [gravity=9.80665]
chemistry balance Fe + O2 -> Fe2O3
chemistry molar mass Ca(OH)2
story fantasy seed=42 hero=Mira
story mystery seed=7 about a missing keeper

Use * for multiplication. Math angles are radians. Physics inputs are SI;
projectile angle is degrees. Formula and unit case matters. Square-bracketed
options in these examples are optional: omit the brackets when using them.
Calculations are bounded; unsupported/undefined results are reported explicitly.
Stories plan valid actions within an authored world, with reproducible seeds.'''

_FILLER = re.compile(
    r"^(?:(?:(?:hey|hi|hello|okay|ok|yo)\s+)?friday\b[\s,!:\u2014-]*"
    r"|(?:please|pls|plz|kindly|just|quickly|now)\s+"
    r"|(?:can|could|would|will)\s+(?:you|u)(?:\s+be\s+able\s+to)?\s+"
    r"|is\s+it\s+possible\s+for\s+you\s+to\s+"
    r"|i\s+was\s+wondering\s+if\s+you\s+(?:can|could|would)\s+"
    r"|(?:i\s+)?(?:want|need|wanna)\s+(?:you\s+)?to\s+"
    r"|i'?d\s+like\s+(?:you\s+)?to\s+|go\s+ahead\s+and\s+)", re.I,
)
_HEADS = {"engine", "math", "calculate", "differentiate", "integrate", "solve", "vector", "matrix", "physics", "chemistry", "story"}


def canonical(message: str) -> str | None:
    """Only strip leading courtesy; never lowercase or split a formula/story payload."""
    if not isinstance(message, str):
        return None
    text = message.strip()
    for _ in range(8):
        stripped = _FILLER.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    if match := re.match(r"^(?:generate|write|tell me)(?:\s+me)?\s+(?:a\s+)?story\b\s*", text, re.I):
        return "story " + text[match.end():]
    parts = text.split(maxsplit=1)
    if not parts:
        return None
    head, tail = parts[0], parts[1] if len(parts) > 1 else ""
    lower = head.casefold()
    if lower in _HEADS:
        if lower == "math":
            op_parts = tail.split(maxsplit=1)
            operation = op_parts[0] if op_parts else ""
            sep, rest = (" ", op_parts[1]) if len(op_parts) == 2 else ("", "")
            if operation.casefold() in {"calculate", "simplify", "expand", "factor", "solve", "differentiate", "integrate", "limit", "vector", "matrix", "stats"}:
                tail = operation.casefold() + sep + rest
        elif lower in {"engine", "vector", "matrix", "physics"}:
            op_parts = tail.split(maxsplit=1)
            operation = op_parts[0] if op_parts else ""
            sep, rest = (" ", op_parts[1]) if len(op_parts) == 2 else ("", "")
            tail = operation.casefold() + sep + rest
        return lower + (" " + tail if tail else "")
    if lower == "limit" and re.search(r"\s+as\s+[a-z]\s*->", tail):
        return "limit " + tail
    if lower == "stats" and tail.startswith(("[", "(")):
        return "stats " + tail
    if lower == "convert" and re.match(r"[+\-\d.(]", tail) and " to " in tail:
        return "convert " + tail
    return None


def match_command(message: str) -> str | None:
    return canonical(message)


def run(command: str) -> ActionResult:
    result = calculate(command)
    # Preserve exact results and procedural prose: no model wording or speech cache.
    return ActionResult(result.success, result.render(), repeatable=False)
