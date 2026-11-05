"""Shared behavioral priorities and learned interruption timing, with no model loop."""
import re
from contextlib import contextmanager
from datetime import datetime

from core.config import config
from core.logger import logger
from services.mind.cognition import cognition

HISTORY_SECONDS = 7 * 86400
REASONS = {
    'cognition_disabled': 'background cognition is disabled', 'attention_unavailable': 'current attention is unavailable',
    'busy': 'your current activity needs attention', 'gaming': 'gaming mode or activity is active',
    'call': 'another app is using the microphone', 'typing': 'you are typing',
    'speaking': 'a spoken reply is in progress', 'listening': 'I am listening to your current reply',
    'pending_reply': 'leaving space for the current exchange', 'owner_request_active': 'finishing your current request first',
    'conversation_disabled': 'you asked me to speak only when addressed',
    'conversation_paused': 'you requested quiet time', 'owner_away': 'giving you time away from the laptop',
    'learned_cooldown': 'recent responses suggest a quieter interval in this activity',
    'commitment_imminent': 'a recorded timed commitment is imminent',
}


def context_key(live, now):
    period = 'night' if now.hour < 6 else 'morning' if now.hour < 12 else 'afternoon' if now.hour < 18 else 'evening'
    # Categories/modes only: no window titles, paths, questions or answer text.
    values = [str(live.get('activity', 'unknown')), str(live.get('mode_name', 'normal')), period]
    return '|'.join(re.sub(r'[^a-z0-9 _-]', '', v.casefold())[:40] for v in values)


class LifeState:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def _db(self):
        with self.store._lock, self.store._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS life_reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT UNIQUE NOT NULL,
                context TEXT NOT NULL, reaction TEXT NOT NULL, at REAL NOT NULL)''')
            yield db

    def feedback(self, context, reaction, source, now=None):
        if not config.COGNITION_ENABLED or reaction not in {'answered', 'shushed', 'ignored'}:
            return
        if not context or not source or len(context) > 130 or not re.fullmatch(r'[a-z0-9 _|-]+', context):
            return
        now = now or datetime.now()
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            if source.startswith('inquiry:'):
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'inquiry_jobs' not in tables or not db.execute(
                        "SELECT 1 FROM inquiry_jobs WHERE id=? AND explicit=0 AND state IN "
                        "('submitted','attempted','failed','answered','ignored','shushed')",
                        (source.split(':')[1],)).fetchone():
                    return  # forgotten/withheld/requested questions cannot train autonomous timing
            db.execute('INSERT OR IGNORE INTO life_reactions(source,context,reaction,at) VALUES(?,?,?,?)',
                       (source[:100], context, reaction, now.timestamp()))
            db.execute('DELETE FROM life_reactions WHERE at<? OR id NOT IN '
                       '(SELECT id FROM life_reactions ORDER BY id DESC LIMIT 500)',
                       (now.timestamp() - HISTORY_SECONDS,))

    def engagement(self, context, now):
        if not config.COGNITION_ENABLED:
            rows = []
        else:
            with self._db() as db:
                rows = db.execute('SELECT reaction,at FROM life_reactions WHERE context=? AND at BETWEEN ? AND ? '
                                  'ORDER BY at DESC,id DESC LIMIT 50',
                                  (context, now.timestamp() - HISTORY_SECONDS, now.timestamp())).fetchall()
        answers = sum(row['reaction'] == 'answered' for row in rows)
        declines = sum(row['reaction'] == 'shushed' for row in rows)
        unanswered = sum(row['reaction'] == 'ignored' for row in rows)
        good, bad = 2., 2.
        streak = []
        for row in rows:
            weight = .5 ** ((now.timestamp() - row['at']) / (3 * 86400))
            if row['reaction'] == 'answered':
                good += weight
            else:
                bad += weight * (2 if row['reaction'] == 'shushed' else .25)
        for row in rows:
            if row['reaction'] == 'answered' or now.timestamp() - row['at'] > 86400:
                break
            streak.append(row)
        cooldown = 0
        if streak:
            refused = sum(row['reaction'] == 'shushed' for row in streak)
            minutes = min(240, 60 * 2 ** min(2, max(0, refused - 1))) if refused else min(120, 15 * len(streak))
            cooldown = streak[0]['at'] + minutes * 60
        return {'answers': answers, 'declines': declines, 'unanswered': unanswered,
                'welcome_estimate': round(good / (good + bad), 2), 'cooldown_until': cooldown,
                'meaning': 'Timing evidence only; an unanswered offer is not rejection or an obligation to reply.'}

    def assess(self, now, known, live, preferences, *, busy=False, mic=False, imminent=False):
        context = context_key(live, now)
        engagement = self.engagement(context, now)
        groups = {key: [] for key in ('current', 'upcoming', 'overdue', 'blocked', 'unresolved', 'active', 'unverified_actions')}
        day, stamp = now.date().isoformat(), now.timestamp()
        for ref, value in known.items():
            kind = value.get('kind')
            if kind == 'outcome_lesson':
                groups['unverified_actions'].append(ref)
            if kind in {'task', 'goal'} and value.get('status') == 'active':
                groups['active'].append(ref)
                if value.get('blocker'):
                    groups['blocked'].append(ref)
            if kind == 'temporal_interpretation' and value.get('status') not in {'completed', 'cancelled'}:
                start, end = value.get('start'), value.get('end')
                group = ('unresolved' if not start or value.get('status') == 'uncertain' else
                         'overdue' if end < day else 'current' if start <= day else 'upcoming')
                groups[group].append(ref)
            if kind in {'deadline', 'reminder'}:
                due = value.get('due_at') if kind == 'reminder' else value.get('due')
                due = datetime.fromisoformat(due).timestamp() if isinstance(due, str) else due
                if isinstance(due, (int, float)):
                    imminent = imminent or -300 <= due - stamp <= 900
                    if due < stamp - 300:
                        groups['overdue'].append(ref)
                    elif due <= stamp + 86400:
                        groups['current'].append(ref)
                    else:
                        groups['upcoming'].append(ref)
        groups = {key: refs[:5] for key, refs in groups.items()}
        review = []
        if not config.COGNITION_ENABLED:
            review.append('cognition_disabled')
        if not live or live.get('state') == 'partly unavailable':
            review.append('attention_unavailable')
        gaming = live.get('mode_name') == 'gaming' or live.get('activity') == 'gaming'
        for flag, reason in ((busy, 'busy'), (gaming, 'gaming'), (mic, 'call'),
                (live.get('idle_band') == 'typing', 'typing'), (live.get('speaking'), 'speaking'),
                (live.get('listening'), 'listening'), (live.get('waiting_for_answer'), 'pending_reply'),
                (any(row.get('kind') in {'request', 'feature_request'} for row in live.get('active_operations', [])), 'owner_request_active')):
            if flag:
                review.append(reason)
        blocks = list(review)
        for flag, reason in ((not preferences.get('on', True), 'conversation_disabled'),
                (preferences.get('paused_until', 0) > stamp, 'conversation_paused'),
                (live.get('away') or live.get('idle_band') == 'away', 'owner_away'),
                (engagement['cooldown_until'] > stamp, 'learned_cooldown'), (imminent, 'commitment_imminent')):
            if flag:
                blocks.append(reason)
        if groups['current']:
            aim, basis = 'support_commitment', groups['current']
        elif groups['unverified_actions']:
            aim, basis = 'check_action_outcome', groups['unverified_actions']
        elif groups['blocked'] or groups['unresolved']:
            aim, basis = 'resolve_uncertainty', (groups['blocked'] + groups['unresolved'])[:5]
        elif groups['overdue']:
            aim, basis = 'check_recorded_status', groups['overdue']
        elif groups['upcoming']:
            aim, basis = 'prepare_for_commitment', groups['upcoming']
        elif groups['active']:
            aim, basis = 'support_owner_priority', groups['active']
        else:
            aim, basis = 'observe', []
        posture = ('quiet' if blocks else 'attentive' if groups['current'] or groups['upcoming'] else
                   'curious' if groups['blocked'] or groups['unresolved'] else
                   'engaged' if engagement['answers'] else 'content')
        reason = ('Respecting your attention: ' + '; '.join(REASONS[block] for block in blocks[:3]) + '.' if blocks else
                  'Review the cited responsibility or uncertainty; a useful question is optional.' if basis else
                  'No pressing responsibility is recorded; observation and silence are appropriate.')
        return {'kind': 'behavioral_state', 'day': day, 'context': context, 'posture': posture,
                'can_review': not review, 'can_initiate': not blocks, 'review_blocks': review,
                'interruption_blocks': blocks, 'reason': reason, 'responsibilities': groups,
                'focus': {'aim': aim, 'basis': basis}, 'engagement': engagement,
                'meaning': 'Software priorities from evidence; not emotion, proof of outcomes or permission to act.'}


life_state = LifeState(cognition)


def current(now=None, *, known=None, live=None, preferences=None, busy=None, mic=None, imminent=False, store=None):
    """Read existing canonical adapters once; consumers may reuse their own snapshots."""
    now = now or datetime.now()
    try:
        from services.mind import talk, cognition_context
        from services.mind.reasoning_store import ReasoningStore
        from services.proactive.watcher import is_busy
        known = ReasoningStore(store or cognition).evidence() if known is None else known
        live = cognition_context.live_state() if live is None else live
        preferences = talk.load() if preferences is None else preferences
        busy = is_busy() if busy is None else busy
        mic = talk.mic_in_use() if mic is None else mic
        return (LifeState(store) if store is not None else life_state).assess(
            now, known, live, preferences, busy=busy, mic=mic, imminent=imminent)
    except Exception as error:
        logger.debug('Behavioral life state unavailable (%s)', type(error).__name__)
        return {'posture': 'quiet', 'can_review': False, 'can_initiate': False,
                'review_blocks': ['state_unavailable'], 'interruption_blocks': ['state_unavailable'],
                'reason': 'Current behavioral context is unavailable; defer optional work.'}


def reaction(pending, event, now):
    """Feedback belongs to the ORIGINAL offered autonomous interruption, never a new activity."""
    if (not pending.get('offered') or pending.get('explicit') or not pending.get('behavior_context')
            or not pending.get('inquiry_id')):
        return
    try:
        source = f"inquiry:{pending['inquiry_id']}"
        life_state.feedback(pending['behavior_context'], event, source, datetime.fromtimestamp(now))
    except Exception as error:
        logger.debug('Interruption timing feedback unavailable (%s)', type(error).__name__)
