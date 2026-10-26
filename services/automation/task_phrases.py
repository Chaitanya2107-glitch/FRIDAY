"""Bounded creation/editing sentences mapped to the existing command grammar.

Only command scaffolding is replaced. Captured names, evidence and task bodies
remain literal; the destination parser retains validation and saved-state checks.
"""
import re


_DAY = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_TIME = r"\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?"
_DURATION = r"\d+(?:\.\d+)?\s*(?:hours?|hrs?|minutes?|mins?)"
_SCORE = r"(?P<got>\d+(?:\.\d+)?)\s*(?:out of|/)\s*(?P<out>\d+(?:\.\d+)?)"
_EXAM = r"(?P<exam>(?:cie|ia|internal|quiz|assignment|test|lab|mid)[\w ]*)"
_WHEN = r"(?:in (?:\d{1,4}|an?|half an?) (?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)|at \d{1,2}(?::\d{2})?\s*(?:[ap]\.?\s?m\.?)?(?: tomorrow)?)"

_PATTERNS = tuple((re.compile(pattern, re.I | re.S), replacement) for pattern, replacement in (
    (rf"schedule (?:a )?(?P<subject>.+?) class on (?P<day>{_DAY}) from (?P<start>{_TIME}) to (?P<end>{_TIME})(?P<room> in (?:room )?[^\r\n]+)?",
     r"add class \g<subject> on \g<day> from \g<start> to \g<end>\g<room>"),
    (rf"put (?P<subject>.+?) on (?:my |the )?timetable for (?P<day>{_DAY}) from (?P<start>{_TIME}) to (?P<end>{_TIME})(?P<room> in (?:room )?[^\r\n]+)?",
     r"add class \g<subject> on \g<day> from \g<start> to \g<end>\g<room>"),
    (rf"take (?P<subject>.+?) off (?:my |the )?(?:timetable|schedule)(?P<day> on {_DAY})?",
     r"remove class \g<subject>\g<day>"),
    (rf"remove (?P<subject>.+?) from (?:my |the )?(?:timetable|schedule)(?P<day> on {_DAY})?",
     r"remove class \g<subject>\g<day>"),
    (rf"(?:record|save|log) {_SCORE} for (?P<subject>.+?) {_EXAM}",
     r"scored \g<got>/\g<out> in \g<subject> \g<exam>"),
    (rf"(?:set|update|change|save|record) (?:my |the )?(?:marks|score) for (?P<subject>.+?) {_EXAM} (?:to|as) {_SCORE}",
     r"scored \g<got>/\g<out> in \g<subject> \g<exam>"),
    (rf"(?:set|change) (?P<app>.+?)'s daily limit to (?P<duration>{_DURATION})",
     r"limit \g<app> to \g<duration> a day"),
    (rf"(?:set|change|update) (?:the |my )?daily limit for (?P<app>.+?) to (?P<duration>{_DURATION})",
     r"limit \g<app> to \g<duration> a day"),
    (rf"give (?P<app>.+?) a daily limit of (?P<duration>{_DURATION})",
     r"limit \g<app> to \g<duration> a day"),
    (r"stop limiting (?P<app>.+)", r"remove the limit on \g<app>"),
    (r"watch (?P<url>https?://\S+) for (?:changes|updates)", r"tell me when \g<url> changes"),
    (r"watch (?P<app>.+?) until it (?:closes|exits|quits)", r"tell me when \g<app> closes"),
    (r"alert me at (?P<percent>\d{1,3})(?:%| percent) battery", r"tell me when battery reaches \g<percent>%"),
    (r"watch (?P<target>[^:\r\n]+?) for text:\s*(?P<text>.+)", r"tell me when \g<target> says \g<text>"),
    (r"watch (?P<target>.+?) for errors", r"tell me when \g<target> logs an error"),
    (r"cancel (?:the |my )?watch on (?P<target>.+)", r"stop watching \g<target>"),
    (rf"(?P<when>{_WHEN}) remind me to (?P<body>.+)", r"remind me \g<when> to \g<body>"),
    (rf"reminder (?P<when>{_WHEN}):\s*(?P<body>.+)", r"remind me \g<when> to \g<body>"),
    (r"replace (?:startup|launch|resume) steps for project (?P<name>[^:\r\n]+?) with (?P<steps>.+)",
     r"set resume steps for \g<name>: \g<steps>"),
    (r"when I return to project (?P<name>[^:\r\n]+?) do:\s*(?P<steps>.+)",
     r"set resume steps for \g<name>: \g<steps>"),
    (r"(?:set|create|add) (?:a )?(?P<priority>low|normal|high) priority goal:\s*(?P<title>.+)",
     r"add goal \g<priority>: \g<title>"),
    (r"track (?:a )?(?:new )?task:\s*(?P<title>.+)", r"start task: \g<title>"),
    (r"(?:create|track|add) (?:a )?task for goal (?P<goal>[^:\r\n]+):\s*(?P<title>.+)",
     r"start task for goal \g<goal>: \g<title>"),
    (r"(?:set|replace|update) (?:the )?(?:steps|plan) for task (?P<reference>[^:\r\n]+?) (?:to|with):\s*(?P<steps>.+)",
     r"plan task \g<reference>: \g<steps>"),
    (r"(?:report|record) (?:a )?completed step for task (?P<reference>[^:\r\n]+):\s*(?P<evidence>.+)",
     r"finish task step \g<reference>: \g<evidence>"),
    (r"mark goal (?P<reference>.+?) as (?:done|finished|completed)", r"complete goal \g<reference>"),
    (r"put goal (?P<reference>.+?) on hold", r"pause goal \g<reference>"),
    (r"mark goal (?P<reference>.+?) as cancel(?:led|ed)", r"cancel goal \g<reference>"),
    (r"continue goal (?P<reference>.+)", r"resume goal \g<reference>"),
    (r"(?:change|set) (?:the )?priority of goal (?P<reference>.+?) to (?P<priority>low|normal|high)",
     r"set goal \g<reference> priority \g<priority>"),
    (r"mark task (?P<reference>[^:\r\n]+?) as blocked(?P<note>:\s*.+)?", r"block task \g<reference>\g<note>"),
    (r"mark task (?P<reference>[^:\r\n]+?) as (?:done|finished|completed)(?P<note>:\s*.+)?", r"complete task \g<reference>\g<note>"),
    (r"put task (?P<reference>[^:\r\n]+?) on hold(?P<note>:\s*.+)?", r"pause task \g<reference>\g<note>"),
    (r"continue task (?P<reference>[^:\r\n]+?)(?P<note>:\s*.+)?", r"resume task \g<reference>\g<note>"),
    (r"mark task (?P<reference>[^:\r\n]+?) as cancel(?:led|ed)(?P<note>:\s*.+)?", r"cancel task \g<reference>\g<note>"),
    (r"(?:show|check|report) (?:my |the )?task progress", "task progress"),
))


def rephrase_task_command(message: str) -> str | None:
    """Return an existing command for an entire explicit sentence, else None.

    Leading request filler is removed by the caller. Anchored scaffolding leaves
    negations, quoted examples, dictation and other commands' payloads alone.
    """
    for pattern, replacement in _PATTERNS:
        if match := pattern.fullmatch(message):
            canonical = match.expand(replacement)
            if replacement.startswith("tell me when") and any(key in match.groupdict() for key in ("target", "app", "url")):
                # Battery/web/automatic watches take precedence in the existing
                # parser. Never turn a literal log or app condition into one.
                from services.watch.asked import match_watch_command

                expected = "watch_web" if "url" in match.groupdict() else "watch_log" if "target" in match.groupdict() else "watch_program"
                parsed = match_watch_command(canonical)
                if not parsed or parsed["action"] != expected:
                    return None
            return canonical
    return None
