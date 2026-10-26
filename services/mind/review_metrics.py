"""Private scalar diagnostics for the existing local review, with no extra inference."""
import asyncio
import contextvars
import json
import math
import time

from core.config import config
from core.errors import ProviderError
from core.logger import logger
from services.mind.cognition import cognition

active = contextvars.ContextVar('local_review_trace', default=None)
METRICS = ('total_duration_ms', 'load_duration_ms', 'prompt_eval_duration_ms', 'eval_duration_ms',
           'prompt_eval_count', 'prompt_eval_cached_count', 'eval_count')


def reason(error, phase):
    cause = error
    for _ in range(6):
        if cause is None: break
        if isinstance(cause, TimeoutError):
            return 'attempt_timeout'
        cause = cause.__cause__
    if isinstance(error, ProviderError): return 'provider_error'
    if phase == 'source_check': return 'source_changed'
    if phase == 'persistence': return 'acceptance_refused'
    return 'validation_failed'


class ReviewTrace:
    def __init__(self, store, *, phase='context'):
        self.store, self.started = store, time.monotonic()
        self.phase, self.state, self.reason = phase, 'cancelled', 'cancelled'
        self.calls, self.rejections, self.accepted = [], 0, {}
        self.startup, self.lease_budget_ms, self.inference_budget_ms = {}, None, 25000
        try:
            self.event = self.store.record('local_review', 'brain', json.dumps({
                'phase': phase, 'reason': 'in_progress', 'elapsed_ms': 0, 'calls': []}),
                status='running', public=False)
        except Exception:
            self.event = None

    def record(self):
        if self.event is None: return
        try:
            text = json.dumps({
                'phase': self.phase, 'reason': self.reason,
                'elapsed_ms': round((time.monotonic() - self.started) * 1000, 2),
                'startup': self.startup, 'lease_budget_ms': self.lease_budget_ms,
                'inference_budget_ms': self.inference_budget_ms,
                'rejections': self.rejections, 'accepted': self.accepted, 'calls': self.calls[:6]})
            with self.store._lock, self.store._connect() as db:
                db.execute("UPDATE events SET text=?,status=?,shortened=? WHERE id=? AND kind='local_review' AND runtime=?",
                           (text[:config.COGNITION_EVENT_CHARS], self.state, int(len(text) > config.COGNITION_EVENT_CHARS),
                            self.event, self.store.runtime))
        except Exception:
            logger.warning('Local review diagnostics unavailable')


async def complete(*args, phase, stage=None, **kwargs):
    from providers.failover import complete_with_failover
    trace = active.get()
    if trace is None:
        return await complete_with_failover(*args, **kwargs)
    trace.phase = phase
    row = {'phase': phase, 'call': len(trace.calls) + 1,
           'prompt_chars': len(args[2]) + sum(len(m.content) for m in args[1]), 'status': 'cancelled'}
    if stage in {'memory_relatedness', 'memory_label'}:
        row['stage'] = stage
    trace.calls.append(row)
    started = time.monotonic()
    try:
        result = await complete_with_failover(*args, **kwargs)
        metrics = getattr(result, 'metadata', {})
        if not isinstance(metrics, dict): metrics = {}
        for key in METRICS:
            value = metrics.get(key)
            row[key] = value if type(value) in (int, float) and 0 <= value <= 1e20 and math.isfinite(value) else None
        why = metrics.get('done_reason')
        row['done_reason'] = why if isinstance(why, str) and why in {'stop', 'length', 'load', 'unload'} else None
        row['response_chars'] = len(result.content)
        if metrics.get('incomplete'):
            trace.reason = row['status'] = 'incomplete_output'
            raise ValueError('Local model output did not finish; nothing accepted')
        row['status'] = 'received'
        return result
    except Exception as error:
        if row['status'] != 'incomplete_output':
            trace.reason = row['status'] = reason(error, phase)
        raise
    finally:
        row['wall_ms'] = round((time.monotonic() - started) * 1000, 2)


def latest(store=None):
    store = store or cognition
    for event in reversed(store.recent(config.COGNITION_MAX_EVENTS)):
        if event['kind'] == 'local_review' and not event['shortened']:
            try:
                data = {'state': event['status'], 'at': event['at'], **json.loads(event['text'])}
                if data['state'] == 'running':
                    if event['runtime'] != store.runtime:
                        data.update(state='interrupted', reason='process_interrupted', elapsed_ms=None)
                    else:
                        data['elapsed_ms'] = round(max(0, time.time() - event['at']) * 1000, 2)
                return data
            except (ValueError, TypeError):
                continue
    return None


def describe(data):
    if not data: return 'No local review timing recorded yet.'
    elapsed = f"{data['elapsed_ms'] / 1000:.2f}s" if data['elapsed_ms'] is not None else 'elapsed time unknown'
    return (f"Last recorded local review: {data['state']} ({data['reason']}); "
            f"{elapsed}, {len(data['calls'])} model calls; "
            f"last phase: {data['phase']}.")
