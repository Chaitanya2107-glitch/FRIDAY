"""Aggregate learning audit. Raw source text never enters the report renderer."""

import asyncio
import re
from datetime import datetime, timedelta

from core.config import config
from core.logger import logger
from services.automation.results import ActionResult
from services.learning.contracts import POLICY_VERSION

_REQUEST = re.compile(r'^(?:show\s+(?:me\s+)?(?:my\s+|the\s+)?)?(?:learning report|training data status)$', re.I)
_FAMILIES = {'command_outcomes', 'command_corrections', 'prediction_feedback', 'habit_feedback',
             'semantic_facts', 'semantic_plans', 'conversation_records', 'conversation_summaries',
             'learned_knowledge', 'thought_patterns', 'owner_reviewed_lessons', 'category_mappings', 'unknown'}
_REASONS = {
    'invalid_time': 'Invalid timestamp', 'future_time': 'Future timestamp',
    'invalid_duration': 'Invalid duration', 'invalid_app': 'Invalid app identity',
    'short_session': 'Session shorter than the settled threshold',
    'sensitive_record': 'Sensitive record withheld', 'missing_fields': 'Required fields missing',
    'inferred_fact': 'Inferred fact awaiting verification', 'unreviewed': 'Awaiting owner review',
    'rejected_review': 'Owner review rejected', 'unsupported_kind': 'Unsupported record type',
    'malformed_record': 'Malformed record', 'unknown_origin': 'App origin unverified',
    'automatic_origin': 'Autonomous app transition', 'system_or_idle': 'System or idle boundary',
    'system_window': 'System window', 'idle_boundary': 'Idle boundary', 'runtime_boundary': 'Runtime boundary',
    'screening_rejected': 'Source screening rejected', 'missing_identity': 'Missing stable identity',
    'duplicate_identity': 'Duplicate identity', 'gap': 'Unobserved gap', 'overlap': 'Overlapping sessions',
}
_COVERAGE = {
    'complete': 'Retained records covered', 'missing': 'Source unavailable or absent',
    'missing_table': 'Source table absent', 'busy_or_unreadable': 'Source busy or unreadable',
    'malformed': 'Malformed source', 'partial': 'Partial source scan',
    'cumulative_baseline_only': 'Cumulative baseline only; individual past events unavailable',
    'complete_with_unknown_origin': 'Historical app origins unverified',
    'unknown_origin': 'Historical app origins unverified',
    'derived_from_knowledge': 'Category mappings inventoried with retained knowledge',
}


def _refresh(now: datetime) -> None:
    from services.learning.service import refresh
    refresh(now=now)


def _report(start: datetime, end: datetime, freeze_key: str | None) -> dict:
    from services.learning.catalog import catalog
    return catalog.report(start, end, freeze_key=freeze_key)


def _category(name: str) -> str:
    if name in _FAMILIES:
        return name
    if name.startswith('activity/'):
        from services.activity.categories import APPS, SITES
        if name.split('/', 1)[1] in set(APPS) | set(SITES) | {'other', 'unknown', 'project', 'browsing'}:
            return name
    return 'unknown'


def _percent(value) -> str:
    return f'{float(value) * 100:.0f}%'


def _accounting_start(end: datetime) -> datetime:
    hour, day = config.TELEGRAM_WEEKLY_HOUR, config.TELEGRAM_WEEKLY_DAY
    if not hour.isdigit() or not 0 <= int(hour) <= 23 or not 0 <= day <= 6:
        # On-demand remains available when scheduled delivery is disabled.
        return (end - timedelta(days=end.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = (end - timedelta(days=end.weekday())).replace(hour=int(hour), minute=0, second=0, microsecond=0)
    cutoff += timedelta(days=day)
    return cutoff - timedelta(days=7) if cutoff >= end else cutoff


def build(now: datetime | None = None, freeze_key: str | None = None,
          start: datetime | None = None, end: datetime | None = None) -> str:
    now = now or datetime.now()
    accounting_end = end or now
    start = start or _accounting_start(accounting_end)
    # Explicit scheduled cutoffs are exclusive. A live request includes the
    # inventory just refreshed at its own clock instant.
    end = end or now + timedelta(microseconds=1)
    _refresh(now)
    data = _report(start, end, freeze_key)
    tracking = data.get('tracking_started')
    try:
        tracked_at = datetime.fromisoformat(tracking) if tracking else None
        if tracked_at:
            start = max(start, min(tracked_at, end))
        tracking = tracked_at.strftime('%Y-%m-%d %H:%M') if tracked_at else 'not started'
    except (TypeError, ValueError):
        tracking = 'unavailable'
    count = lambda key: int(data.get(key, 0))
    lines = ['🧠 Learning data quality (local, rule-screened)', '', '📅 Reporting window',
             f'• Period: {start:%Y-%m-%d %H:%M} through {end:%Y-%m-%d %H:%M} (laptop local time; cutoff excluded)',
             f'• Tracking started: {tracking}', '', '📦 Source records',
             f'• Categories — Active: {count("categories_active")}; Created: {count("categories_created")}',
             f'• Collected: {count("collected")}', f'• Appropriate: {count("appropriate")}',
             f'• Excluded: {count("excluded")}', f'• Quarantined: {count("quarantined")}',
             f'• Pending screening: {count("pending_screening")}',
             f'• Historical backfill: {count("backfilled")} (separate from collected)',
             f'• Revisions: {count("revisions")}; Removed: {count("removed")}']
    for category in data.get('categories', []):
        lines.append(f'• {_category(category["name"])}: {int(category.get("collected", 0))} collected records')
    lines.extend(['', '🧹 Screening', '• Appropriate means passed source rules; it does not guarantee factual truth.'])
    reasons = data.get('reasons', {})
    for reason, total in sorted(reasons.items(), key=lambda item: -item[1])[:6]:
        lines.append(f'• {_REASONS.get(reason, "Other screening reason")}: {int(total)}')
    lines.extend(['', '🎯 Next-app transition examples', f'• Eligible: {count("eligible_examples")}',
                  f'• Used for training: {count("used_training")}', f'• Evaluated: {count("evaluated")}',
                  f'• Eligible dataset available at cutoff: {int(data.get("eligible_examples_available", count("eligible_examples")))} '
                  '(stock; Eligible above counts new examples in this period).',
                  '• Unique examples, not repetitions; training/evaluation counts can overlap across runs.',
                  f'• Policy: {POLICY_VERSION}; settled sessions ≥{config.LEARNING_MIN_SESSION_SECONDS} seconds; '
                  f'unobserved gap ≤{config.LEARNING_MAX_GAP_SECONDS} seconds.',
                  '• Facts, conversations and forecast confirmations alone are not observed next-app labels.'])
    if not int(data.get('eligible_examples_available', count('eligible_examples'))):
        lines.append('• No eligible observed transitions yet. Unknown app origin, autonomous actions and continuity '
                     'boundaries can exclude transitions; counting remains available while attributable data accumulates.')
    eligibility_reasons = data.get('eligibility_reasons', {})
    if eligibility_reasons:
        lines.extend(['', '🔎 Current dataset eligibility diagnostics',
                      '• Observations/boundaries; not additive with record counts.'])
        for reason, total in sorted(eligibility_reasons.items(), key=lambda item: -item[1])[:6]:
            lines.append(f'• {_REASONS.get(reason, "Other eligibility reason")}: {int(total)}')
    lines.extend(['', '⚙️ Training'])
    training = data.get('latest_training')
    if training and training.get('purged_crossing_examples'):
        lines.append(f'• Examples crossing the training cutoff withheld: {int(training["purged_crossing_examples"])}.')
    if not training:
        lines.append('• No measured training run recorded yet. Training needs 300 earlier and 100 evaluation '
                     'examples, with at least two target classes; counting remains available.')
    elif training.get('status') == 'skipped':
        skip_reasons = {'insufficient_training_examples': 'fewer than 300 earlier eligible examples',
                        'insufficient_evaluation_examples': 'fewer than 100 evaluation examples',
                        'insufficient_target_classes': 'fewer than two target classes',
                        'fitting_failed': 'model fitting failed',
                        'insufficient_examples': 'insufficient eligible examples',
                        'source_unavailable': 'source data unavailable; no new data fitted'}
        reason = skip_reasons.get(training.get('reason'), 'clean-data checks did not pass')
        fallback = ('The previous evaluated model remains in charge.' if training.get('in_charge') == 'model'
                    else 'Counting remains available.')
        lines.append(f'• Latest training skipped: {reason}. '
                     f'Required: 300 earlier, 100 evaluation examples and at least two classes. {fallback}')
    else:
        model, baseline = training.get('model') or {}, training.get('counting') or {}
        if all(key in model and key in baseline for key in ('top1', 'top3')):
            lines.append(f'• Measured next-app accuracy — model top-1 {_percent(model["top1"])}, top-3 {_percent(model["top3"])}; '
                         f'counting top-1 {_percent(baseline["top1"])}, top-3 {_percent(baseline["top3"])}.')
        lines.append('• Promotion: ' + ('evaluated model selected.' if training.get('in_charge') == 'model' else 'counting retained.'))
    measured = data.get('latest_measured_training')
    if measured and (not training or training.get('status') != 'completed'):
        model, baseline = measured.get('model') or {}, measured.get('counting') or {}
        if all(key in model and key in baseline for key in ('top1', 'top3')):
            lines.append(f'• Last measured accuracy — model top-1 {_percent(model["top1"])}, top-3 {_percent(model["top3"])}; '
                         f'counting top-1 {_percent(baseline["top1"])}, top-3 {_percent(baseline["top3"])} (earlier completed run).')
    # Fingerprints are generated internally; refuse arbitrary source strings.
    version = data.get('dataset_version') or (training or {}).get('dataset_version', (training or {}).get('dataset_fingerprint', ''))
    if re.fullmatch(r'[0-9a-f]{8,64}', str(version)):
        lines.append('• Latest dataset: ' + str(version)[:16])
    diagnostics = {}
    for status in data.get('coverage', {}).values():
        description = _COVERAGE.get(status, 'Source coverage limited')
        diagnostics[description] = diagnostics.get(description, 0) + 1
    if diagnostics:
        lines.extend(['', '📡 Source coverage'])
        lines.extend(f'• {description}: {total}' for description, total in diagnostics.items())
    return '\n'.join(lines)


async def try_handle(message: str) -> ActionResult | None:
    if not _REQUEST.fullmatch(message.strip()):
        return None
    try:
        return ActionResult(True, await asyncio.to_thread(build), repeatable=False)
    except Exception as error:
        logger.warning('Learning report unavailable: %s', type(error).__name__)
        return ActionResult(False, 'I could not read the learning audit just now. Try again shortly.', repeatable=False)
