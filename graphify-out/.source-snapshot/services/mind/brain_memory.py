"""Dated owner reports with question/answer provenance, shared by local cognition."""
import uuid
from contextlib import contextmanager
from datetime import datetime

from core.config import config
from services.mind.cognition import cognition, redact


class BrainMemory:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def schema(db):
        db.execute('''CREATE TABLE IF NOT EXISTS owner_episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_key TEXT UNIQUE NOT NULL,
                channel TEXT NOT NULL, question TEXT NOT NULL, text TEXT NOT NULL,
                noted TEXT NOT NULL, inquiry_id INTEGER)''')
        if 'recall_withheld' not in {row[1] for row in db.execute('PRAGMA table_info(owner_episodes)')}:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            if 'recall_withheld' not in {row[1] for row in db.execute('PRAGMA table_info(owner_episodes)')}:
                db.execute('ALTER TABLE owner_episodes ADD COLUMN recall_withheld INTEGER NOT NULL DEFAULT 0')
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='temporal_situations'").fetchone():
                    db.execute("UPDATE owner_episodes SET recall_withheld=1 WHERE 'owner_episode:'||id IN "
                               "(SELECT source_key FROM temporal_situations WHERE superseded_by IS NOT NULL)")
        if 'inquiry_id' not in {row[1] for row in db.execute('PRAGMA table_info(owner_episodes)')}:
            if not db.in_transaction:
                db.execute('BEGIN IMMEDIATE')
            if 'inquiry_id' not in {row[1] for row in db.execute('PRAGMA table_info(owner_episodes)')}:
                db.execute('ALTER TABLE owner_episodes ADD COLUMN inquiry_id INTEGER')

    @contextmanager
    def _db(self):
        with self.store._lock, self.store._connect() as db:
            self.schema(db)
            yield db

    def remember(self, text, *, question='', channel='chat', source=None, now=None, inquiry_id=None):
        if not config.COGNITION_ENABLED or not text.strip():
            return None
        source = source or uuid.uuid4().hex
        now = now or datetime.now()
        with self._db() as db:
            inserted = db.execute('INSERT OR IGNORE INTO owner_episodes(source_key,channel,question,text,noted,inquiry_id) VALUES(?,?,?,?,?,?)',
                       (source, channel, redact(question[:1000]), redact(text[:4000]), now.isoformat(),
                        inquiry_id if type(inquiry_id) is int and inquiry_id > 0 else None))
            changed = inserted.rowcount > 0
            ident = db.execute('SELECT id FROM owner_episodes WHERE source_key=?', (source,)).fetchone()[0]
            db.execute('DELETE FROM owner_episodes WHERE id IN (SELECT id FROM owner_episodes ORDER BY id DESC LIMIT -1 OFFSET 500)')
        if changed:
            self.store.record('owner_episode', channel, 'Owner report retained with its original date and question.', public=False)
        return ident

    @staticmethod
    def _episode(row):
        return {**({'inquiry_id': row['inquiry_id']} if 'inquiry_id' in row.keys() and row['inquiry_id'] is not None else {}),
                'id': f"owner_episode:{row['id']}", 'kind': 'owner_answer' if row['question'] else 'owner_message',
                'source': 'owner_report' if row['question'] else 'owner_utterance', 'channel': row['channel'], 'question': row['question'],
                'text': row['text'], 'noted': row['noted']}

    def evidence(self, limit=20):
        if not config.COGNITION_ENABLED:
            return {}
        with self._db() as db:
            rows = db.execute('SELECT * FROM owner_episodes ORDER BY id DESC LIMIT ?', (min(50, max(1, limit)),)).fetchall()
            from services.mind.dialogue import Dialogue
            hidden = Dialogue.hidden_sources(db)
            result = {}
            for row in rows:
                if row['id'] in hidden:
                    continue
                value = {**self._episode(row), 'question': row['question'][:500], 'text': row['text'][:1200]}
                if row['inquiry_id'] and row['channel'] in {'chat', 'voice'}:
                    from services.mind.inquiry import Inquiry
                    context = Inquiry.date_answer_context(db, row['inquiry_id'], row['question'], row['noted'])
                    if context:
                        value['date_clarification'] = context
                context = Dialogue.answer_context(db, self._episode(row))
                if context:
                    value['date_clarification'] = context
                result[value['id']] = value
            return result

    def recall(self, query, *, channel='chat', now=None, limit=4):
        """Synchronous callers get literal selection, without unreviewed semantic matches."""
        from services.mind.recall import retrieve
        return retrieve(self, query, channel=channel, limit=limit, semantic=False)

    async def recall_checked(self, query, *, channel='chat', limit=4, deadline=None):
        from services.mind.recall_review import checked
        return await checked(self, query, channel=channel, limit=limit, deadline=deadline)

    def valid_recall(self, rows, *, channel='chat'):
        from services.mind.recall import revalidate
        with self.store._lock:
            return revalidate(self, rows, channel=channel)


brain_memory = BrainMemory(cognition)
