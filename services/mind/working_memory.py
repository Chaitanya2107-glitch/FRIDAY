"""A source-backed view of selected work and original reports; never a plan executor."""

import json
import sqlite3

from core.config import config
from core.logger import logger
from services.mind.cognition import cognition, redact
from services.mind.reasoning_store import fingerprint

MAX_CHARS = 4800


class WorkingMemory:
    def __init__(self, store):
        self.store = store

    def snapshot(self, *, channel='chat'):
        if not config.COGNITION_ENABLED:
            return {'available': False, 'reason': 'cognition_disabled'}
        from services.mind.brain_memory import BrainMemory
        from services.mind.workspace import Workspace
        from services.mind.dialogue import Dialogue
        from services.mind.temporal_memory import TemporalMemory
        from services.mind import reference_context
        from services.mind.recall import _pool

        scope = 'telegram' if channel == 'telegram' else 'local'
        try:
            memory = BrainMemory(self.store)
            with Workspace(self.store)._db() as db:
                BrainMemory.schema(db)
                db.commit()
                db.execute('BEGIN')
                epoch = Dialogue._epoch(db)
                focus, versions = [], {}
                topic, topic_token = None, None
                if scope == 'local':
                    for selected in db.execute("SELECT kind,target FROM workspace_focus WHERE scope='local' ORDER BY kind"):
                        kind, target = selected['kind'], selected['target']
                        if kind not in {'task', 'goal'}:
                            continue
                        table = 'workspace_tasks' if kind == 'task' else 'workspace_goals'
                        row = db.execute(f'SELECT * FROM {table} WHERE id=?', (target,)).fetchone()
                        if row is None:
                            continue
                        source = dict(row)
                        ref = f'{kind}:{target}'
                        versions[ref] = fingerprint(source)
                        item = {'id': ref, 'title': redact(source['title'])[:200], 'status': source['status'],
                                'source': 'owner_selected_work', 'meaning': 'Saved owner-reported progress, not independent completion proof.'}
                        if kind == 'task':
                            steps = json.loads(source['steps'])
                            cursor = source['cursor']
                            item.update(next_step=redact(steps[cursor])[:200] if 0 <= cursor < len(steps) else '',
                                        done=cursor, total=len(steps), blocker=redact(source['blocker'] or '')[:300])
                        else:
                            item['priority'] = source['priority']
                        focus.append(item)
                    saved = reference_context.read(db, 'commitment_topic')
                    if saved and saved['payload'].get('epoch') == epoch:
                        target = saved['payload'].get('target', '')
                        if target.startswith('temporal:') and target.split(':')[-1].isdigit():
                            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='temporal_situations'").fetchone()
                            row = db.execute('SELECT * FROM temporal_situations WHERE id=? AND superseded_by IS NULL',
                                             (int(target.split(':')[-1]),)).fetchone() if exists else None
                            if row:
                                current = TemporalMemory._row(row)
                                if fingerprint(current) == saved['payload'].get('version'):
                                    topic = {key: current.get(key) for key in ('id', 'subject', 'status', 'start', 'end', 'source')}
                                    topic['meaning'] = 'Explicitly selected saved commitment; interpretation of an owner report.'
                                    versions[target], topic_token = fingerprint(current), saved['token']
                pool = _pool(memory, channel, connection=db)
                reports = sorted(pool.values(), key=lambda row: (row['noted'], int(row['id'].split(':')[-1])), reverse=True)[:3]
                reports = [{key: row[key] for key in ('id', 'kind', 'source', 'channel', 'question', 'text', 'noted',
                            'excerpt_truncated', 'meaning')} for row in reports]
                for row in reports:
                    row['text'], row['question'] = redact(row['text']), redact(row['question'])
                data = {'available': True, 'scope': scope, 'focus': focus, 'commitment': topic, 'recent_reports': reports,
                        'meaning': 'Selected work is explicit. Recent reports are historical evidence, not an inferred active topic or permission.'}
                while len(json.dumps(data, ensure_ascii=False)) > MAX_CHARS and reports:
                    reports.pop()
                # Read original sources and selected context under one SQLite snapshot.
                signature = fingerprint({'epoch': epoch, 'versions': versions, 'topic_token': topic_token,
                                         'scope': scope, 'reports': reports})
                return {**data, 'signature': signature}
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, IndexError) as error:
            logger.debug('Working memory unavailable (%s)', type(error).__name__)
            return {'available': False, 'reason': 'source_unavailable'}

    def revalidate(self, snapshot, *, channel='chat'):
        if not snapshot.get('available'):
            return None
        current = self.snapshot(channel=channel)
        return current if current.get('available') and current['signature'] == snapshot.get('signature') else None

    def describe(self, *, channel='chat'):
        data = self.snapshot(channel=channel)
        if not data.get('available'):
            return 'Working memory is unavailable; no context has been inferred.'
        parts = ['Working memory (saved source context):']
        for item in data['focus']:
            text = f"Selected {item['id']}: {item['title']} ({item['status']})."
            if item.get('next_step'):
                text += f" Recorded next step: {item['next_step']}"
            parts.append(text)
        if data['commitment']:
            item = data['commitment']
            parts.append(f"Selected commitment: {item['subject']} ({item['status']}; {item['start'] or 'date unresolved'}).")
        if not data['focus'] and data['commitment'] is None:
            parts.append('No task or commitment is explicitly selected.')
        for item in data['recent_reports']:
            parts.append(f"Original {item['channel']} report dated {item['noted']}: {item['text']}" +
                         (' [Incomplete excerpt.]' if item['excerpt_truncated'] else ''))
        parts.append('These are owner reports and selections; they do not establish current activity or authorize actions.')
        return '\n'.join(parts)


working_memory = WorkingMemory(cognition)
