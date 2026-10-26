"""Missing decision inputs, not a question bank or permission to act."""
import re

from services.mind.reasoning_store import fingerprint


def normalized(value):
    return ' '.join(re.findall(r'\w+', str(value).casefold()))


def gaps(known):
    focus = known.get('focus:local', {}).get('targets', {})
    selected = {f'{kind}:{ident}' for kind, ident in focus.items()}
    result = []
    for ref, row in known.items():
        kind = row.get('kind')
        if kind == 'task' and row.get('status') in {'active', 'blocked'} and (
                row.get('blocker') or row.get('status') == 'blocked'):
            semantic = {key: row.get(key) for key in ('title', 'status', 'blocker', 'steps', 'cursor', 'goal_id')}
            for key in ('title', 'blocker'):
                semantic[key] = normalized(row.get(key) or '')
            ident, subject = ref + ':blocker', row.get('title', 'Recorded task')
            missing = 'blocker_status_or_timing' if row.get('blocker') else 'blocker_identity'
            goal = known.get(f"goal:{row.get('goal_id')}", {})
            rank = 0 if ref in selected or f"goal:{row.get('goal_id')}" in selected else 1 if goal.get('priority') in {3, 'high'} else 2
        elif kind == 'temporal_interpretation' and row.get('status') in {'planned', 'uncertain', 'postponed'} and (
                not row.get('start') or not row.get('end')) and not row.get('superseded_by'):
            subject = row.get('subject', '')
            if not subject:
                continue
            semantic = {key: row.get(key) for key in ('status', 'start', 'end', 'date_phrase')}
            semantic['subject'] = normalized(subject)
            ident = 'commitment:' + fingerprint(normalized(subject))[:20] + ':date'
            missing, rank = 'commitment_date_if_known', 2
        else:
            continue
        result.append({'id': ident, 'version': fingerprint(semantic), 'basis': [ref],
                       'subject': str(subject)[:160], 'missing': missing, 'rank': rank})
    # ponytail: bounded first increment; task blockers and undated commitments only.
    unique, ambiguous = {}, set()
    for row in result:
        if row['id'] in unique and unique[row['id']]['version'] != row['version']:
            ambiguous.add(row['id'])
        unique.setdefault(row['id'], row)
    return sorted((row for ident, row in unique.items() if ident not in ambiguous),
                  key=lambda row: (row['rank'], row['id']))
