"""Requested, scoped local review using the executive's existing lease and budget."""
import asyncio
import time
from datetime import datetime

from core.config import config
from services.mind import executive, reasoning
from services.mind.reasoning_store import ReasoningStore, fingerprint


def attention():
    from services.mind.cognition import cognition, _turn
    state = executive.attention_state()
    life = state.get('life_state', {})
    blocks = set(life.get('review_blocks', [])) - {'owner_request_active'}
    if (blocks or not life.get('can_review', True) and not life.get('review_blocks')
            or any(state.get(key) for key in ('speaking', 'listening', 'waiting_for_answer'))):
        raise ValueError('Attention defers local review')
    # The requesting turn is foreground work; other active operations still defer.
    if any(row['kind'] in {'request', 'feature_request'} and row['turn_id'] != _turn.get() for row in cognition.active()):
        raise ValueError('Another owner request is active')
    return state


async def review(dialogue, ident):
    control = executive.ExecutiveControl(dialogue.store)
    memory = ReasoningStore(dialogue.store)
    now = datetime.now()
    if not control.status(now)['enabled']:
        return
    try:
        state = await asyncio.to_thread(attention)
        with dialogue._db() as db:
            row = db.execute('SELECT * FROM dialogue_clarifications WHERE id=?', (ident,)).fetchone()
            payload = dialogue._valid(db, row)
            source, target = payload['answer']['id'], payload['target']
        known = await asyncio.to_thread(memory.evidence)
        if source not in known or target not in known or not known[source].get('date_clarification'):
            return
        bounded = {source: known[source], target: known[target]}
        situation = await asyncio.to_thread(control.capture, now, known=bounded, attention=state, intention='conversation_update')
        await asyncio.to_thread(control.enqueue, situation, now, preserve_running=True)
        job = await asyncio.to_thread(control.claim, now, signature=situation['signature'])
        if not job or job['signature'] != situation['signature']:
            return
        started = time.monotonic()

        def owned(db):
            if (not config.COGNITION_ENABLED or not config.REASONING_ENABLED or not config.COGNITIVE_REVIEW_ENABLED
                    or not control._valid(db, job, now.timestamp() + time.monotonic() - started)):
                raise ValueError('The local review was cleared, disabled or expired')
            current = db.execute('SELECT * FROM dialogue_clarifications WHERE id=?', (ident,)).fetchone()
            if not current or current['state'] != 'answered':
                raise ValueError('The conversation was cleared')

        def guard(db):
            owned(db)
            current = db.execute('SELECT * FROM dialogue_clarifications WHERE id=?', (ident,)).fetchone()
            dialogue._valid(db, current)

        def ready():
            attention()
            current = memory.evidence()
            if any(key not in current or fingerprint(current[key]) != fingerprint(value) for key, value in bounded.items()):
                raise ValueError('The reviewed owner sources changed')
            with control._db() as db:
                guard(db)

        def save(report, noted, evidence):
            ready()
            if (report.facts or report.memories or report.conclusions or report.questions or
                    any(value.source != source or value.supersedes != [target] for value in report.situations)):
                raise ValueError('A conversation review cannot change unrelated memory')
            def finalize(db):
                owned(db)
                db.execute("UPDATE executive_reviews SET state='completed',updated=? WHERE id=? AND token=?",
                           (now.timestamp() + time.monotonic() - started, job['id'], job['token']))
            return memory.save(report, noted, evidence, guard=guard, finalize=finalize)

        result = await reasoning.analyze('', now=now, cognitive=True, evidence=bounded, save=save,
                                         deadline=started + executive.LEASE_SECONDS - 1, ready=ready)
        finished = datetime.fromtimestamp(now.timestamp() + time.monotonic() - started)
        await asyncio.to_thread(control.finish, job, 'completed' if result['status'] == 'completed' else 'unavailable', finished)
    except (ValueError, OSError):
        return  # The retained answer is still eligible for the normal background review.
