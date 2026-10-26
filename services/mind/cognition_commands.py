"""Local factual introspection without exposing notification text to an AI."""

import re
from datetime import datetime

from services.automation.command_words import normalize_command
from services.automation.results import ActionResult
from services.mind.cognition import cognition, mark_introspection
from services.mind.cognition_context import live_state

_QUERIES = {
    'brain_status': r'brain status|question status|thinking status|why (?:did|do|are) you (?:not )?ask(?:ing)?(?: me)? (?:that|this|questions)|why did you stay silent',
    "executive_status": r"executive status|cognitive review status",
    "executive_on": r"executive review on|enable cognitive review",
    "executive_off": r"executive review off|disable cognitive review",
    "executive_why": r"why did you decide that|show (?:your )?last executive decision",
    "notification_status": r"(?:notification|reminder delivery|notification brain) status|show (?:my |your |the )?notification decisions",
    "notification_why": r"why did you (?:not )?(?:send|show) (?:that|the last) notification|why (?:was|is) (?:that|the) notification (?:suppressed|deferred|withheld)",
    "reminder_retry": r"retry (?:failed|held|withheld|deferred) reminders",
    "layers": r"brain layers|show (?:your |my |the )?(?:brain |cognitive )?layers|layer status",
    "reply": r"what did you (?:just |last )?say|what was your last (?:answer|reply)|repeat (?:your |the )?last (?:answer|reply)",
    "notification": r"what notification did you (?:just )?send|what was (?:that|your last|the last) notification|what did you notify me about",
    "telegram_message": r"what did you (?:just )?send (?:on|through|in|to) telegram|what was your last telegram message",
    "action": r"what action did you (?:just |last )?(?:take|run)|what did you just do",
    "question": r"what did you ask me|what (?:question )?did you just ask|what was your last question",
    "state": r"cognition status|show (?:your |my )?cognition|what are you doing right now|what do you know is happening",
}


def match_command(message: str) -> str | None:
    text = normalize_command(message)
    return next((kind for kind, pattern in _QUERIES.items() if re.fullmatch(pattern, text, re.I)), None)


def run(kind: str, *, remote: bool = False) -> ActionResult:
    mark_introspection()
    if kind == 'brain_status':
        if remote:
            return ActionResult(False, 'Brain decisions and dialogue memory are local-only. Ask me at the laptop.', repeatable=False)
        from services.mind.inquiry import inquiry
        from services.mind.brain_memory import brain_memory
        from services.mind import cognitive_runtime
        from services.mind.temporal_memory import temporal_memory
        status = inquiry.status()
        last = status['last_decision']
        text = (f"Local brain reasoning: {'enabled' if status['enabled'] else 'disabled'}. "
                f"Event-driven attention: {'running' if cognitive_runtime.running() else 'not running'}. "
                f"Owner dialogue episodes available: {len(brain_memory.evidence(50))}. "
                f"Automatic questions today: {status['automatic_questions_today']}/{status['daily_question_ceiling']} ceiling; "
                f"at least {status['minimum_gap_minutes']} minutes apart. There is no question quota or scheduled interview.")
        if last:
            text += f" Last inquiry decision: {last['state']}. {last['reason']}"
            purpose = (status.get('last_question') or {}).get('purpose')
            if purpose:
                text += (f" Most recent question purpose ({status['last_question']['state']}): {purpose['decision']} Conditional possibilities: "
                         f"if {purpose['if_answer_a']['answer']}: {purpose['if_answer_a']['next_step']}; "
                         f"if {purpose['if_answer_b']['answer']}: {purpose['if_answer_b']['next_step']}. "
                         "These are proposals, not assumed answers or actions.")
        view = temporal_memory.snapshot(limit=4)
        for group in ('current', 'upcoming', 'unresolved'):
            entries = view[group]
            if entries:
                text += f" {group.title()} owner-reported commitments: " + '; '.join(
                    f"{row['subject']} ({row['start'] or 'date unresolved'}; {row['status']})" for row in entries) + '.'
        from services.mind.life_state import current
        behavior = current()
        text += (f" Behavioral state: {behavior['posture']}. Attention permits silent review: "
                 f"{'yes' if behavior['can_review'] else 'no'}; optional interruptions: "
                 f"{'yes' if behavior['can_initiate'] else 'no'}. {behavior['reason']}")
        from services.mind.outcome_learning import outcome_learning
        text += ' ' + outcome_learning.describe()
        from services.mind.consolidation import consolidation
        memory = consolidation.status()
        text += (f" Memory consolidation: {memory['active']} active historical threads; "
                 f"{memory['retired']} retired; {memory['sources']} original source snapshots. "
                 "Extractive connections share the local executive review budget.")
        from services.mind.review_metrics import latest, describe
        text += ' ' + describe(latest())
        return ActionResult(True, text, memory_message='Reviewed local brain attention and inquiry status.', repeatable=False)
    if kind in {"executive_status", "executive_on", "executive_off", "executive_why"}:
        if remote:
            return ActionResult(False, "Executive cognition controls and decisions are local-only. Ask me at the laptop.", repeatable=False)
        from services.mind.executive import executive
        if kind in {"executive_on", "executive_off"}:
            executive.set_enabled(kind == "executive_on")
        return ActionResult(True, executive.describe(why=kind == "executive_why"),
                            memory_message="Reviewed or changed local executive cognition controls.", repeatable=False)
    if kind in {"notification_status", "notification_why", "reminder_retry"}:
        if remote:
            return ActionResult(False, "Notification decisions and recovery controls are local-only. Ask me at the laptop.",
                                repeatable=False)
        from services.mind import notification_status
        if kind == "reminder_retry":
            uncertain = any(row["status"] == "uncertain" for row in notification_status.reminders.delivery_status(100))
            count = notification_status.reminders.retry_failed()
            text = (f"Queued {count} reminder{'s' if count != 1 else ''} for a fresh brain review. "
                    "No notification has been sent by this request.")
            if uncertain:
                text += " An interrupted submission may already have arrived; retry can duplicate that uncertain delivery."
        else:
            text = notification_status.describe(latest_only=kind == "notification_why")
        return ActionResult(True, text, memory_message="Reviewed notification brain status or queued recovery locally.",
                            repeatable=False)
    if kind == "layers":
        from services.mind.layers import describe
        return ActionResult(True, describe(), repeatable=False)
    if kind == "state":
        state = live_state()
        active = state.get("active_operations", [])
        text = (f"My shared cognition is tracking {state.get('activity', 'unknown activity')}. "
                f"Mood: {state.get('mood', 'unknown')}. "
                f"Telegram: {'configured' if state.get('telegram_configured') else 'not configured'}. "
                f"Waiting for a reply: {'yes' if state.get('waiting_for_answer') else 'no'}. "
                f"Speaking: {'yes' if state.get('speaking') else 'no'}; "
                f"listening: {'yes' if state.get('listening') else 'no'}; "
                f"thinking: {'yes' if state.get('thinking') else 'no'}. "
                f"Operations in progress: {len(active)}.")
        return ActionResult(True, text, repeatable=False)
    event = cognition.latest(kind)
    if not event:
        return ActionResult(False, f"I haven't recorded a {kind.replace('_', ' ')} yet.", repeatable=False)
    if remote and not event["public"]:
        return ActionResult(False, "That event's contents are local-only. Ask me at the laptop.", repeatable=False)
    when = datetime.fromtimestamp(event["at"]).strftime("%I:%M %p")
    text = f"{kind.replace('_', ' ').title()} at {when} ({event['channel']}, {event['status']}):\n{event['text']}"
    if event["shortened"]:
        text += "\n(The recorded text was shortened.)"
    return ActionResult(True, text, memory_message="Recalled a recorded cognition event locally.", repeatable=False)
