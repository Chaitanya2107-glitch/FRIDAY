"""Owner inspection and explicit approval of reasoning proposals."""

import asyncio
import json
import re
from datetime import datetime

from services.automation.command_words import normalize_command
from services.automation.results import ActionResult
from services.mind.reasoning_store import reasoning_store


def match_command(text):
    text = normalize_command(text)
    if re.fullmatch(r"reasoning status|show (?:your )?reasoning|what (?:have you|did you) infer|show reasoning proposals", text, re.I):
        return {"action": "show"}
    if match := re.fullmatch(r"(?P<action>apply|reject) reasoning proposal (?P<id>\d+)", text, re.I):
        return {"action": match["action"].lower(), "id": match["id"]}
    if re.fullmatch(r"reconsider (?:my situation|my plans|my facts)", text, re.I):
        return {"action": "review"}
    return None


async def run(parsed):
    from services.mind import reasoning, reasoning_effects
    from services.automation.intent import remote_request, telegram_owner
    if remote_request.get() and not (telegram_owner.get() and parsed["action"] == "show"):
        return ActionResult(False, 'Reasoning evidence and controls are local-only. Ask me at the laptop.', repeatable=False)
    try:
        if parsed["action"] == "review":
            result = await reasoning.analyze("")
            return ActionResult(result["status"] == "completed", "Reconsidered the current evidence." if result["status"] == "completed"
                                else "Reasoning is unavailable; no new changes were confirmed.", repeatable=False)
        if parsed["action"] == "show":
            data = await asyncio.to_thread(reasoning_store.context)
            lines = [f"Owner fact {fact['id']} ({fact['certainty']}, told {fact['noted'][:10]}): {fact['quote']}" for fact in data["facts"]]
            for claim in data["conclusions"]:
                lines.append(f"Conclusion {claim['id']} ({claim['kind']}, {claim['status']}, estimated confidence {claim['confidence']:.0%}): "
                             f"{claim['text']} Evidence: {', '.join(claim['evidence'])}." +
                             (f" Apply with: apply reasoning proposal {claim['id']}." if claim["status"] == "proposed" else ""))
            for memory in data.get('memories', []):
                lines.append(f"Historical memory thread (inferred topic: {memory['subject']}): " + '; '.join(
                    f"{source['id']} ({source['noted']}): " +
                    (f"answer to {source['question']!r}: " if source.get('question') else '') + source['text']
                    for source in memory['excerpts']) + '. Original reports, not verified current facts.')
            return ActionResult(True, "\n".join(lines) or "No current reasoning conclusions recorded.",
                                memory_message="Reviewed local reasoning facts and proposals.", repeatable=False)
        ident = int(parsed["id"])
        if parsed["action"] == "reject":
            claim = await asyncio.to_thread(reasoning_store.get, ident, datetime.now())
            if not claim or claim["status"] != "proposed":
                raise ValueError("No current pending proposal with that ID.")
            if not await asyncio.to_thread(reasoning_store.claim, ident):
                raise ValueError("That proposal was already consumed.")
            await asyncio.to_thread(reasoning_store.finish, ident, "rejected")
            from services.mind.cognition import cognition
            private = any(ref.startswith(('action_outcome:', 'outcome_lesson:', 'inquiry:', 'consolidation:', 'owner_episode:')) for ref in claim['evidence'])
            text = f"Owner rejected reasoning proposal {ident}" + ('.' if private else f": {claim['text']}")
            cognition.record("reaction", "brain", text, public=not private)
            return ActionResult(True, f"Rejected reasoning proposal {ident}.", repeatable=False)
        outcome = await asyncio.to_thread(reasoning_effects.apply, ident)
        return ActionResult(True, outcome, repeatable=False)
    except ValueError as error:
        return ActionResult(False, str(error), repeatable=False)
    except Exception:
        return ActionResult(False, "The reasoning change could not be confirmed. Check the current service state.", repeatable=False)
