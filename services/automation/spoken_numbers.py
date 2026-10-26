"""Normalize spoken numbers in explicit duration and selection slots only.

No imports from command_words/device_commands: both use this helper upstream.
Payloads, clock times, dates, names and ambiguous quantities stay unchanged.
"""
import re


_SMALL = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
    range(20),
))
_TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
_ORDINALS = dict(zip(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth".split(),
    range(1, 20),
)) | dict(zip("twentieth thirtieth fortieth fiftieth sixtieth seventieth eightieth ninetieth".split(), range(20, 100, 10)))


def _under_hundred(parts: list[str]) -> int | None:
    if len(parts) == 1:
        return _SMALL.get(parts[0], _TENS.get(parts[0]))
    if len(parts) == 2 and parts[0] in _TENS and 1 <= _SMALL.get(parts[1], -1) <= 9:
        return _TENS[parts[0]] + _SMALL[parts[1]]
    return None


def _number(text: str, *, ordinal: bool = False) -> int | None:
    parts = text.casefold().replace("-", " ").split()
    if ordinal and parts[-1] in _ORDINALS:
        end = _ORDINALS[parts[-1]]
        if len(parts) == 1:
            return end
        if len(parts) == 2 and parts[0] in _TENS and end <= 9:
            return _TENS[parts[0]] + end
        return None
    if len(parts) >= 2 and parts[:2] == ["a", "hundred"]:
        parts[0] = "one"
    if len(parts) >= 2 and parts[0] in _SMALL and 1 <= _SMALL[parts[0]] <= 9 and parts[1] == "hundred":
        rest = parts[2:]
        if not rest:
            return _SMALL[parts[0]] * 100
        if rest[0] == "and":
            rest = rest[1:]
        tail = _under_hundred(rest)
        return _SMALL[parts[0]] * 100 + tail if tail and tail > 0 else None
    return _under_hundred(parts)


_N = r"(?P<n>[a-z]+(?:(?: +|-)[a-z]+)*?)"
_SHORT = r"(?:seconds?|secs?|s|minutes?|mins?|m)"
_LONG = r"(?:minutes?|mins?|hours?|hrs?)"
_ALL_UNITS = r"(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)"
_PC = r"(?:\s+(?:(?:the|my|this)\s+)?(?:laptop|pc|computer|system|machine))?"
_READING = r"(?:my |the )?reading list"

# Each pattern captures one bounded slot. Reminder text after 'to' is never scanned.
_DURATIONS = tuple(re.compile(pattern, re.I) for pattern in (
    rf"remind me in {_N}\s+(?P<unit>{_ALL_UNITS})\s+to\s+.+",
    rf"(?:set|create|add|make|schedule) (?:a |an |me a )?(?:new )?(?:reminder|notification|alert) (?P<prep>in|for) {_N}\s+(?P<unit>{_ALL_UNITS})\s+to\s+.+",
    rf"(?:wait|pause|sleep)(?: for)? {_N}\s+(?P<unit>{_SHORT})[.!?]*",
    rf"(?:shut ?down|turn off|power off|switch off){_PC} in {_N}\s+(?P<unit>{_LONG}|seconds?|secs?)[.!?]*",
    rf"(?:restart|reboot){_PC} in {_N}\s+(?P<unit>{_LONG})[.!?]*",
    rf"(?:pause|mute|snooze|silence|hold) (?:the |my |your )?nudges for {_N}\s+(?P<unit>{_LONG})[.!?]*",
    rf"(?:limit|cap) .+? to {_N}\s+(?P<unit>{_LONG})(?: (?:a|per|each) day| daily)?[.!?]*",
    rf"set (?:a |an )?(?:daily )?(?:time )?limit of {_N}\s+(?P<unit>{_LONG})(?: (?:a|per) day)? (?:for|on) .+",
))
_INDICES = tuple(re.compile(pattern, re.I) for pattern in (
    rf"open (?:search )?result {_N}[.!?]*",
    rf"(?:show|reveal|open) (?:me )?(?:result|file|number) {_N} (?:is )?in (?:the )?(?:folder|explorer|file explorer)[.!?]*",
    rf"(?:open|done with|finished|remove|delete|cross off) {_READING} (?:item |number )?{_N}[.!?]*",
    rf"(?:open|done with|finished|remove|delete|cross off) (?:item |number )?{_N} (?:from|on|in) {_READING}[.!?]*",
    rf"open saved reading item {_N}[.!?]*",
    rf"mark reading item {_N} as (?:read|finished)[.!?]*",
    rf"(?:cancel|delete|remove|stop) (?:the |my )?reminder (?:number )?{_N}[.!?]*",
    rf"(?:restore|copy|paste|use|get) clipboard (?:item|entry|number) {_N}[.!?]*",
))


def normalize_command_numbers(message: str) -> str:
    """Replace confident positive values (1–999) without touching other text.

    Fractional, compound-unit, mixed-digit and malformed values are left to the
    existing parser. Bare 'open six' stays an app name; selectors need a label.
    """
    for patterns, ordinal in ((_DURATIONS, False), (_INDICES, True)):
        for pattern in patterns:
            if match := pattern.fullmatch(message):
                number = 1 if not ordinal and match["n"].casefold() in {"a", "an"} else _number(match["n"], ordinal=ordinal)
                if number is not None and 1 <= number <= 999:
                    left, right = match.span("n")
                    if match.groupdict().get("prep", "").casefold() == "for":
                        # Native reminder 'for 5pm' means a clock; durations need 'in'.
                        start, end = match.span("prep")
                        return message[:start] + "in" + message[end:left] + str(number) + message[right:]
                    return message[:left] + str(number) + message[right:]
                return message
    return message
